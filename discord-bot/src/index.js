import { verifyKey } from "discord-interactions";

const InteractionType = {
  PING: 1,
  APPLICATION_COMMAND: 2
};

const InteractionResponseType = {
  PONG: 1,
  DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE: 5
};

const DISCORD_API = "https://discord.com/api/v10";
const MESSAGE_LIMIT = 1850;

function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8"
    }
  });
}

function formatPct(value) {
  const n = Number(value || 0);
  return `${n.toFixed(2).replace(".", ",")}%`;
}

function splitLongLine(line, maxLength) {
  if (line.length <= maxLength) {
    return [line];
  }

  const result = [];
  let remaining = line;

  while (remaining.length > maxLength) {
    let cut = remaining.lastIndexOf(" ", maxLength);

    if (cut < Math.floor(maxLength * 0.6)) {
      cut = maxLength;
    }

    result.push(remaining.slice(0, cut));
    remaining = remaining.slice(cut).trimStart();
  }

  if (remaining) {
    result.push(remaining);
  }

  return result;
}

function splitMessage(text, maxLength = MESSAGE_LIMIT) {
  const expanded = text
    .split("\n")
    .flatMap((line) => splitLongLine(line, maxLength));

  const chunks = [];
  let current = "";

  for (const line of expanded) {
    const candidate = current ? `${current}\n${line}` : line;

    if (candidate.length > maxLength && current) {
      chunks.push(current);
      current = line;
    } else {
      current = candidate;
    }
  }

  if (current) {
    chunks.push(current);
  }

  return chunks.length ? chunks : ["Sin datos."];
}

function formatSubstories(data) {
  const items = Array.isArray(data.subhistorias)
    ? data.subhistorias
    : [];

  if (!items.length) {
    return "SUBHISTORIAS — YAKUZA 4\n\nNo hay datos de subhistorias.";
  }

  const byProtagonist = new Map();

  for (const item of items) {
    const protagonist = item.protagonist || "Otros";

    if (!byProtagonist.has(protagonist)) {
      byProtagonist.set(protagonist, []);
    }

    byProtagonist.get(protagonist).push(item);
  }

  const lines = ["SUBHISTORIAS — YAKUZA 4", ""];

  for (const [protagonist, group] of byProtagonist.entries()) {
    lines.push(`**${String(protagonist).toUpperCase()}**`);

    for (const item of group) {
      const id = item.id ?? "?";
      const name = item.name || `Subhistoria ${id}`;

      lines.push(
        `${id}. ${name}: ${formatPct(item.pct_translated)} traducido / ${formatPct(item.pct_reviewed)} revisado`
      );
    }

    lines.push("");
  }

  const total = items.reduce(
    (acc, item) => {
      acc.total += Number(item.total || 0);
      acc.translated += Number(item.translated || 0);
      acc.reviewed += Number(item.reviewed || 0);
      return acc;
    },
    { total: 0, translated: 0, reviewed: 0 }
  );

  const translatedPct = total.total
    ? (total.translated * 100) / total.total
    : 0;

  const reviewedPct = total.total
    ? (total.reviewed * 100) / total.total
    : 0;

  lines.push("**TOTAL SUBHISTORIAS**");
  lines.push(`Traducción: ${formatPct(translatedPct)}`);
  lines.push(`Revisión: ${formatPct(reviewedPct)}`);

  return lines.join("\n").trim();
}

function formatHostess(data) {
  const h = data.hostess || {};
  const individual = Array.isArray(h.individual)
    ? h.individual
    : [];

  const lines = [
    "HOSTESS — YAKUZA 4",
    ""
  ];

  if (individual.length) {
    for (const item of individual) {
      lines.push(
        `${item.name}: ${formatPct(item.pct_translated)} traducido / ${formatPct(item.pct_reviewed)} revisado`
      );
    }

    lines.push("");
  }

  lines.push("**TOTAL HOSTESS**");
  lines.push(
    `${formatPct(h.pct_translated)} traducido / ${formatPct(h.pct_reviewed)} revisado`
  );
  lines.push(
    `Líneas: ${Number(h.translated || 0)}/${Number(h.total || 0)} traducidas`
  );
  lines.push(
    `Revisadas: ${Number(h.reviewed || 0)}/${Number(h.total || 0)}`
  );

  return lines.join("\n");
}

function formatStory(data) {
  const h = data.historia || {};
  const protagonists = Array.isArray(h.protagonistas)
    ? h.protagonistas
    : [];

  const lines = [
    "HISTORIA PRINCIPAL — YAKUZA 4",
    ""
  ];

  if (protagonists.length) {
    for (const item of protagonists) {
      lines.push(
        `${item.name}: ${formatPct(item.pct_translated)} traducido / ${formatPct(item.pct_reviewed)} revisado`
      );
    }

    lines.push("");
  }

  lines.push("**TOTAL HISTORIA PRINCIPAL**");
  lines.push(
    `${formatPct(h.pct_translated)} traducido / ${formatPct(h.pct_reviewed)} revisado`
  );
  lines.push(
    `Líneas: ${Number(h.translated || 0)}/${Number(h.total || 0)} traducidas`
  );
  lines.push(
    `Revisadas: ${Number(h.reviewed || 0)}/${Number(h.total || 0)}`
  );

  return lines.join("\n");
}

async function loadProgress(env) {
  const response = await fetch(env.PROGRESS_URL, {
    headers: {
      "User-Agent": "DD-Y4-Discord-Bot/1.0",
      "Accept": "application/json"
    }
  });

  if (!response.ok) {
    throw new Error(
      `No se pudo descargar progress.json: HTTP ${response.status}`
    );
  }

  return await response.json();
}

async function editOriginal(interaction, content) {
  const url =
    `${DISCORD_API}/webhooks/${interaction.application_id}/${interaction.token}/messages/@original`;

  const response = await fetch(url, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      content,
      allowed_mentions: { parse: [] }
    })
  });

  if (!response.ok) {
    const body = await response.text();

    throw new Error(
      `No se pudo editar la respuesta: HTTP ${response.status} ${body}`
    );
  }
}

async function sendFollowup(interaction, content) {
  const url =
    `${DISCORD_API}/webhooks/${interaction.application_id}/${interaction.token}`;

  const response = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      content,
      allowed_mentions: { parse: [] }
    })
  });

  if (!response.ok) {
    const body = await response.text();

    throw new Error(
      `No se pudo enviar follow-up: HTTP ${response.status} ${body}`
    );
  }
}

async function deliver(interaction, text) {
  const chunks = splitMessage(text);

  await editOriginal(interaction, chunks[0]);

  for (const chunk of chunks.slice(1)) {
    await sendFollowup(interaction, chunk);
  }
}

async function processCommand(interaction, env) {
  try {
    const progress = await loadProgress(env);
    const command =
      String(interaction.data?.name || "").toLowerCase();

    let text;

    switch (command) {
      case "subhistorias":
        text = formatSubstories(progress);
        break;

      case "hostess":
        text = formatHostess(progress);
        break;

      case "historia":
        text = formatStory(progress);
        break;

      default:
        text = "Comando desconocido.";
        break;
    }

    await deliver(interaction, text);
  } catch (error) {
    console.error(error);

    try {
      await editOriginal(
        interaction,
        "No pude consultar el progreso del repositorio en este momento."
      );
    } catch (secondaryError) {
      console.error(secondaryError);
    }
  }
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") {
      return new Response(
        "DD-Y4 Discord Bot OK",
        { status: 200 }
      );
    }

    if (request.method !== "POST") {
      return new Response(
        "Method Not Allowed",
        { status: 405 }
      );
    }

    const signature =
      request.headers.get("x-signature-ed25519");

    const timestamp =
      request.headers.get("x-signature-timestamp");

    if (!signature || !timestamp) {
      return new Response(
        "Missing Discord signature",
        { status: 401 }
      );
    }

    const rawBody =
      await request.clone().arrayBuffer();

    const valid = await verifyKey(
      rawBody,
      signature,
      timestamp,
      env.DISCORD_PUBLIC_KEY
    );

    if (!valid) {
      return new Response(
        "Bad request signature",
        { status: 401 }
      );
    }

    const interaction = await request.json();

    if (interaction.type === InteractionType.PING) {
      return jsonResponse({
        type: InteractionResponseType.PONG
      });
    }

    if (
      interaction.type !==
      InteractionType.APPLICATION_COMMAND
    ) {
      return jsonResponse(
        {
          type: 4,
          data: {
            content: "Tipo de interacción no soportado.",
            allowed_mentions: { parse: [] }
          }
        },
        200
      );
    }

    ctx.waitUntil(
      processCommand(interaction, env)
    );

    return jsonResponse({
      type:
        InteractionResponseType
          .DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE
    });
  }
};
