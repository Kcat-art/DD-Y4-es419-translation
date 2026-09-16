const token = process.env.DISCORD_TOKEN;
const applicationId = process.env.DISCORD_APPLICATION_ID;
const guildId = process.env.DISCORD_GUILD_ID || "";

if (!token) {
  throw new Error("Falta DISCORD_TOKEN");
}

if (!applicationId) {
  throw new Error("Falta DISCORD_APPLICATION_ID");
}

const commands = [
  {
    type: 1,
    name: "subhistorias",
    description: "Muestra el progreso de traducción y revisión de las subhistorias."
  },
  {
    type: 1,
    name: "hostess",
    description: "Muestra el progreso del contenido Hostess."
  },
  {
    type: 1,
    name: "historia",
    description: "Muestra el progreso de la historia principal."
  }
];

const endpoint = guildId
  ? `https://discord.com/api/v10/applications/${applicationId}/guilds/${guildId}/commands`
  : `https://discord.com/api/v10/applications/${applicationId}/commands`;

const response = await fetch(endpoint, {
  method: "PUT",
  headers: {
    "Content-Type": "application/json",
    "Authorization": `Bot ${token}`
  },
  body: JSON.stringify(commands)
});

const text = await response.text();

if (!response.ok) {
  console.error(text);
  throw new Error(`Discord respondió HTTP ${response.status}`);
}

console.log("Comandos registrados correctamente.");
console.log(guildId ? `Servidor de prueba: ${guildId}` : "Registro global");
console.log(text);
