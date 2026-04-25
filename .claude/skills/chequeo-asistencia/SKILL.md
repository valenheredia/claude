---
name: chequeo-asistencia
description: >
  Verifica la asistencia del personal de Active Clean SRL y genera el informe diario.
  Usá este skill siempre que el usuario mencione: chequear asistencia, verificar turnos,
  control de fichajes, ausencias del día, tardanzas, reemplazos urgentes, o cuando pida
  correr/ejecutar la rutina de asistencia. También disparar si el usuario dice "corré el
  chequeo", "revisá los turnos de hoy", o cualquier variante relacionada con el control
  de presencia del equipo de limpieza. Usar también cuando se ejecuta en modo automático
  sin interacción humana (routine de Claude Code).
---

# Verificación de turnos — Active Clean SRL

Lee Connecteam vía API REST, cruza turnos vs fichajes, crea el archivo del día en Google
Drive a partir del template y envía resumen via conector Gmail.

> Si necesitás entender la estructura de la planilla o ver ejemplos reales de llenado,
> leer `references/ejemplos-planilla.md` antes del Paso 4.

---

## Estructura de archivos en Google Drive

```
Mi unidad / ACTIVE CLEAN / Operaciones / Registro checklist /
├── checklist_operativo_daily.xlsx   ← TEMPLATE (nunca modificar)
├── Abril 2026/
│   ├── 22/04/2026.xlsx
│   ├── 23/04/2026.xlsx
│   └── ...
├── Mayo 2026/
│   └── ...
```

- El template está en la raíz de `Registro checklist`
- Cada día se crea un archivo nuevo en la carpeta del mes en curso
- Nombre del archivo: `DD/MM/AAAA.xlsx` (ej: `25/04/2026.xlsx`)
- Nombre de la carpeta del mes: `[Mes en español] AAAA` (ej: `Abril 2026`, `Mayo 2026`)

---

## Paso 1 — Leer turnos del día (Connecteam)

```python
import requests
from datetime import date

api_key = "0ee55bea-c948-4c5f-8321-8eefa1a576a5"
hoy = date.today().isoformat()
headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

turnos   = requests.get("https://api.connecteam.com/shifts/v1/shifts",
                        headers=headers, params={"startDate": hoy, "endDate": hoy}).json()
fichajes = requests.get("https://api.connecteam.com/time-clock/v1/time-entries",
                        headers=headers, params={"startDate": hoy, "endDate": hoy}).json()
```

Extraer de **turnos**: `userId`, `jobId`, `scheduledStart`, `scheduledEnd`
Extraer de **fichajes**: `userId`, `jobId`, `clockIn`, `clockOut`

---

## Paso 2 — Cruzar datos

Por cada turno, buscar fichaje con mismo `userId` + `jobId`:

| Condición | Col E | Col F | Col G |
|-----------|-------|-------|-------|
| clockIn ≤ scheduledStart + 10 min | X | OK | — |
| clockIn > scheduledStart + 10 min | X | TARDE | hora real (HH:MM) |
| Sin clockIn y ya pasó scheduledStart | - | NO | "No fichó" |
| clockOut = null (turno activo) | X | ACTIVO | — |
| Sin turno programado | — | — | — |

**Ignorar siempre:** Walter Benitez y Rodrigo Martinez.

---

## Paso 3 — Crear archivo del día (conector Google Drive)

Usando el conector Google Drive:

1. Navegar a `Mi unidad / ACTIVE CLEAN / Operaciones / Registro checklist`
2. Verificar si ya existe el archivo de hoy (`DD/MM/AAAA.xlsx`) en la carpeta del mes en curso
   - Si existe → abrirlo y continuar en Paso 4
   - Si no existe → continuar con los pasos siguientes
3. Determinar la carpeta del mes en curso en español (ej: `Abril 2026`, `Mayo 2026`)
   - Si la carpeta no existe → crearla
4. Duplicar el archivo `checklist_operativo_daily.xlsx` (template)
5. Renombrar la copia con la fecha de hoy: `DD/MM/AAAA.xlsx`
6. Mover la copia a la carpeta del mes en curso

---

## Paso 4 — Completar la planilla

> Si tenés dudas sobre qué va en cada columna o cómo manejar casos especiales,
> leer `references/ejemplos-planilla.md`.

Abrir el archivo del día y completar cada fila con servicio según el cruce del Paso 2:

- **Col D**: nombre del operario (si no está ya)
- **Col E**: X / - / —
- **Col F**: OK / TARDE / NO / ACTIVO / —
- **Col G**: hora real si tardanza, "No fichó" si ausente, vacío si OK
- **Col I**: acción tomada ("Cubierto con X", "Reprogramado")
- **Col J**: Cubierto / Programar / Reprogramar / vacío

**Reglas:**
- No borrar lo que ya está escrito — solo completar celdas vacías
- Col G: texto conciso, máx ~60 caracteres
- Sección PENDIENTES: agregar una fila por cada P1/P2 sin resolver

---

## Paso 5 — Evaluar prioridad de ausentes

Para cada ausente (Col E = `-`, Col F = `NO`), completar Col I:

**P1 — REEMPLAZO URGENTE:**
Bilder, Vonderk, Esparza, Correa, Triunvirato 5375

**P2 — RESOLVER EN EL DÍA:**
Amenábar 3208, Ciudad de la Paz, Core oficina, Conesa 2958, Vonderk depósito

**P3 — PUEDE ESPERAR:**
Resto de los servicios

---

## Paso 6 — Enviar resumen por mail (conector Gmail)

Usar el conector Gmail para enviar a `valenheredia13@gmail.com`.

**Asunto:** `Asistencia HH:MM — DD/MM/AAAA`

**Cuerpo:**
```
AUSENCIAS:
- [Nombre] | [Servicio] | [Horario] | [Prioridad]
(o "Ninguna")

TARDANZAS:
- [Nombre] | [Servicio] | [Hora prog.] → [Hora real]
(o "Ninguna")

RESUMEN:
Cubiertos: X / Total: X
P1 sin cubrir: X
P2 sin cubrir: X
```
