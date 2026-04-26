# DD-Y4-es419-translation

Repositorio para la traducción de **Yakuza 4 Remastered** de [Dragones de Dojima](https://x.com/Dragones_Dojima).

![Banner Yakuza 4](https://images.steamusercontent.com/ugc/40077233591204845/7637A6F89DDCC5B9CD86D895A7FDF6FEE5F4EE12/)
![Progreso global](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Kcat-art/DD-Y4-es419-translation/main/assets/progress/global_badge.json)
![Traducción](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Kcat-art/DD-Y4-es419-translation/main/assets/progress/translation_badge.json)
![Revisión](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/Kcat-art/DD-Y4-es419-translation/main/assets/progress/review_badge.json)
<!-- PROGRESS_SECTION_START -->
## Progreso del proyecto

**Progreso global:** 1,39%

**Traducción global:** 3016/108289 (2,79%)  
**Revisión global:** 0/108289 (0,00%)

| Área | Traducción | Revisión |
|---|---:|---:|
| Diálogos | 53/81372 (0,07%) | 0/81372 (0,00%) |
| Cinemáticas | 2960/3050 (97,05%) | 0/3050 (0,00%) |
<!-- PROGRESS_SECTION_END -->

# Paso 0: Obtener el token de acceso

Para que el programa pueda sincronizar y subir cambios al repositorio, cada traductor/revisor necesita un **token personal de GitHub**.
El token funciona como una contraseña especial para que el programa pueda conectarse a GitHub.

# Paso 1: Configurando el traductor y los archivos DLL

## 1. Descargar el programa

Descarga el programa **Traductor Dragones de Dojima** y ubícalo en la carpeta del juego.

El programa está pensado para la versión de **Steam** de Yakuza 4 Remastered.

Ruta de ejemplo:

```txt
C:\Program Files (x86)\Steam\steamapps\common\Yakuza 4
```

## 2. Ubicar los archivos DLL

Los archivos `.dll` deben estar en la misma carpeta principal del juego, junto al ejecutable.

La carpeta debería verse así:

```txt
Yakuza 4\
  Yakuza4.exe
  dinput8.dll
  qcpuchk.dll
  qcpuchk_orig.dll
  Traductor Dragones de Dojima.exe
```

## 3. Abrir el traductor

Ejecuta:

```txt
Traductor Dragones de Dojima.exe
```

Al abrirlo por primera vez, entra en:

```txt
Config.
```

Allí debes configurar:

* tu **token de GitHub**;
* tu **nickname**;
* la **clave de revisor**, solo si eres revisor.

Después de llenar los datos, pulsa **Guardar**.

---

# Paso 2: Sincronización inicial y primera compilación

Después de guardar la configuración, pulsa:

```txt
Sincronizar
```

El programa descargará los archivos actuales del repositorio.

Cuando termine la sincronización, deberían aparecer los archivos listos para traducir en el panel izquierdo.

## Primera compilación

Si tienes los archivos necesarios en:

```txt
translation_work\source
```

el programa realizará una compilación inicial de los archivos.

Este proceso puede tardar, especialmente la primera vez.

Si no tienes los archivos de `translation_work\source`, puede aparecer un error de compilación. Ese error no impide traducir; solamente significa que el programa no pudo compilar los archivos del juego en ese momento.

Mientras el programa esté sincronizando o compilando, no lo cierres.

---

# Paso 3: Cómo traducir

Una vez sincronizado el proyecto, ya puedes empezar a traducir.

## 1. Elegir un archivo

En el panel izquierdo verás las carpetas y archivos del proyecto.

Los colores indican el estado de cada archivo:

| Color          | Estado                   |
| -------------- | ------------------------ |
| Amarillo claro | Sin traducir o pendiente |
| Azul claro     | Traducido                |
| Verde claro    | Revisado                 |

Cada archivo muestra:

* estado;
* líneas traducidas;
* porcentaje de avance.

Selecciona un archivo pendiente para empezar.

---

## 2. Elegir una línea

En la parte central aparecerá la lista de líneas del archivo seleccionado.

Puedes seleccionar cualquier línea pendiente.

También puedes usar el botón:

```txt
Siguiente pendiente
```

para avanzar más rápido entre líneas sin traducir.

---

## 3. Traducir

Al seleccionar una línea verás:

* el texto original en inglés;
* el texto japonés, si está disponible;
* el campo de traducción.

Escribe la traducción en el campo:

```txt
Traducción
```

Cuando termines, pulsa:

```txt
Guardar
```

El botón **Guardar** solo guarda el cambio localmente en tu equipo.

---

## 4. Subir cambios

Cuando hayas terminado de traducir varias líneas, pulsa:

```txt
Subir
```

El programa enviará tus cambios a GitHub.

---

# Historial de traducciones

El programa conserva un historial de traducciones por línea.

Esto significa que si dos traductores modifican la misma línea, no se pierde ninguna propuesta.

Ejemplo:

1. El traductor X traduce una línea.
2. Luego el traductor Y abre esa misma línea.
3. El traductor Y verá la traducción actual de X.
4. Si Y cambia la traducción y la sube, la versión de X se conserva.
5. La versión de Y queda como la más reciente.
6. El revisor puede elegir cuál versión dejar como final.

La traducción más reciente es la que queda activa, pero las versiones anteriores siguen disponibles en el historial.

---

# Revisión

Los revisores pueden usar el botón:

```txt
Historial
```

Desde ahí pueden:

* ver versiones anteriores de una línea;
* ver quién hizo cada propuesta;
* ver la fecha de cada versión;
* aplicar una versión como traducción final;
* borrar una propuesta del historial si no debe conservarse.

---

# Búsqueda global

El botón:

```txt
Buscar global
```

permite buscar texto en todos los archivos del proyecto.

El programa mostrará una lista con todas las coincidencias encontradas.

Puedes usarlo para:

* encontrar frases repetidas;
* revisar términos;
* buscar líneas concretas;
* comparar cómo se tradujo una expresión en otros archivos.

---

# Recomendaciones para traducir

* Mantén consistencia con nombres, lugares y términos recurrentes.
* No borres variables ni símbolos especiales.
* Respeta placeholders como:

```txt
{0}
%s
%d
\n
```

---

# Créditos

Proyecto de traducción realizado por **Dragones de Dojima**.

## Coordinador del proyecto

- [Karu](https://github.com/KaruCentral)

## Romhacking

- Brazil Alliance
- [Kcat0](https://github.com/Kcat-art)

## Edición gráfica

- Crazy56

## Revisores

- KeyBlueG
- sasha malvada
- dani64amv

## Traductores

- lauU
- Brasi
- [Master](https://github.com/MastterCry)
