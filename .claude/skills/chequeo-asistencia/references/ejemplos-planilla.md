# Ejemplos reales de la planilla — Active Clean

## Estructura de columnas (fila de servicios)

| Col | Nombre | Valores posibles |
|-----|--------|-----------------|
| A | # | Número de fila |
| B | Horario | 6:00 / 7:00 / 9:00 / 12:30 / 15:00 / 16:00 / vacío |
| C | Servicio | Nombre del cliente/sede |
| D | Operario asignado | Nombre completo / NADIE / vacío |
| E | Asistencia | X / - / vacío |
| F | Fichaje | OK / NO / ok / vacío |
| G | Comentario / Novedad | Texto libre |
| H | Insumos pendientes | Texto libre |
| I | Acción tomada | Texto libre |
| J | Estado final | Cubierto / Programar / Reprogramar / vacío |

**Sobre Col E (Asistencia):** acepta X o x (mayúscula/minúscula indistinto) = presente. Guión (-) = ausente/novedad. Vacío = sin dato.
**Sobre Col F (Fichaje):** OK/ok = fichaje correcto. NO = no fichó. Vacío = sin dato o turno sin fichaje requerido.

---

## Secciones de la planilla

```
CLIENTES DIRECTOS     → filas 5–25 aprox
MENTRAU SA            → filas 26–32 aprox  
CORE — SERVICIOS      → filas 33–55 aprox
CORE — FRANQUICIAS    → filas 56–60 aprox
INSUMOS DEL DÍA       → tabla separada abajo
PENDIENTES Y NOVEDADES DEL DÍA → tabla separada
CIERRE DEL DÍA — 18:00 → checklist final
```

---

## Ejemplo 1 — Día con novedades mixtas (22/04/2026, Miércoles)

Casos representativos de ese día:

```
Servicio               | Operario          | E | F   | Comentario
-----------------------|-------------------|---|-----|-----------------------------
Bilder                 | Silvia Sosa       | X | ok  | (normal)
Ciudad de la Paz 2880  | Daniela Gonzalez  | X | OK  | (normal)
Olazábal 1870          | Javier Rojas      | - | OK  | Vacaciones Javi, cubre Daniela. 1H DE MENOS
MENTRAU Depósito       | Carolina Leonhardt| - |     | Ausente con aviso 2hs antes → Reprogramado
DIDCOM REFUERZO        | Rosana Pereira    | X | ok  | Fila extra de refuerzo (sin número)
CORE Montevideo 1648   | Alejandra Pucheta | - | NO  | Llegando tarde, no está fichado
CORE Borges 2259       | NADIE             | - |     | Renuncia Erika Gomez, falta reemplazo
CORE Cullen 4987       | Hugo Flores       | - |     | Reprogramado para mañana
```

**Patrones a notar:**
- Operario = NADIE: servicio sin asignar, siempre ausente
- Col E = `-` con Col F = `OK`: fue pero con novedad (vacaciones, reemplazo, etc.)
- Filas sin número (#): refuerzos o turnos extra, igual se completan
- Col J vacía cuando se resuelve en el momento; "Programar" o "Reprogramar" cuando queda pendiente

---

## Ejemplo 2 — Día con más movimiento (24/04/2026, Viernes)

```
Servicio               | Operario          | E | F | Comentario
-----------------------|-------------------|---|---|-----------------------------
Monroe                 | Sol Gomez         | x |   | Llegó 26 minutos tarde → TARDE en Col F
Zapiola                | Jose Luis Franco  | x |   | Descuento 50% por quejas, incidencia registrada
Vázquez Seguros        | Marisa Alegre     | - |   | Ausencia médica → Cubierto con Daniela (Col I)
Triunvirato 5375       | Hugo Flores       |   |   | Vacío = sin dato al momento del chequeo
CORE Borges 2259       | NADIE             | - |   | Reprogramar, falta gente
CORE Santa Fé 3390     | Jose Luis Franco  | - |   | Reprogramar, dos días seguidos
CORE Holmberg 1932     | Daniela Gonzalez  | - |   | Recupera turno de ayer, cubre Vázquez por Marisa
CORE Cabildo 157       | Daniela Gonzalez  | - |   | Cubierto con Jose Luis, deja libre Santa Fe
```

**Patrones a notar:**
- Tardanza: Col E = X, Col F = vacío o texto con hora → completar Col G con hora real y Col F con "TARDE"
- Un operario puede aparecer en múltiples filas el mismo día (reasignaciones)
- Col G acepta texto libre: "Llegó 26 minutos tarde", "Ausencia médica", "Cubre X por Y"
- Cuando Col E y F están vacías al momento del chequeo: turno aún no empezó o sin datos → dejar vacío, no asumir ausencia

---

## Reglas de llenado para Claude

1. **No borrar lo que ya está escrito** — solo completar celdas vacías o corregir con datos de Connecteam
2. **Respetar mayúsculas/minúsculas** del resto del día al escribir OK/NO/TARDE
3. **Col G es texto libre** — escribir la novedad de forma concisa (máx ~60 caracteres)
4. **Col I = acción tomada** — solo completar si ya hay una acción concreta (ej: "Cubierto con Daniela")
5. **Col J = estado final** — usar: Cubierto / Programar / Reprogramar / dejar vacío
6. **Ignorar filas sin Servicio** (filas totalmente vacías = separadores)
7. **Sección PENDIENTES**: agregar una fila por cada P1/P2 sin resolver, con descripción y acción requerida
