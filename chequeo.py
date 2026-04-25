import os, requests, smtplib, io, copy
from datetime import date, datetime
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2.service_account import Credentials
import openpyxl
import json

# --- Credenciales ---
CONNECTEAM_API_KEY = os.environ["CONNECTEAM_API_KEY"]
GOOGLE_SHEET_ID    = os.environ["GOOGLE_SHEET_ID"]       # ID del template
GMAIL_SENDER       = os.environ["GMAIL_SENDER"]
GMAIL_RECIPIENT    = os.environ["GMAIL_RECIPIENT"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
SA_JSON            = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

MESES_ES = {
    1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
    7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"
}

P1 = ["bilder","vonderk","esparza","correa","triunvirato 5375"]
P2 = ["amenábar 3208","ciudad de la paz","core oficina","conesa 2958","vonderk depósito"]
IGNORAR = ["walter benitez","rodrigo martinez"]

# --- Google Drive auth ---
creds = Credentials.from_service_account_info(
    json.loads(SA_JSON),
    scopes=["https://www.googleapis.com/auth/drive"]
)
drive = build("drive", "v3", credentials=creds)

hoy        = date.today()
nombre_archivo = hoy.strftime("%d/%m/%Y") + ".xlsx"
nombre_carpeta = f"{MESES_ES[hoy.month]} {hoy.year}"

# --- Buscar o crear carpeta del mes ---
def buscar_id(nombre, tipo, parent=None):
    q = f"name='{nombre}' and mimeType='{tipo}' and trashed=false"
    if parent:
        q += f" and '{parent}' in parents"
    r = drive.files().list(q=q, fields="files(id)").execute()
    files = r.get("files", [])
    return files[0]["id"] if files else None

# Carpeta raíz: buscar "Registro checklist"
registro_id = buscar_id("Registro checklist", "application/vnd.google-apps.folder")

# Buscar o crear carpeta del mes
carpeta_mes_id = buscar_id(nombre_carpeta, "application/vnd.google-apps.folder", registro_id)
if not carpeta_mes_id:
    meta = {"name": nombre_carpeta, "mimeType": "application/vnd.google-apps.folder",
            "parents": [registro_id]}
    carpeta_mes_id = drive.files().create(body=meta, fields="id").execute()["id"]

# --- Buscar o crear archivo del día ---
archivo_id = buscar_id(nombre_archivo, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", carpeta_mes_id)

if not archivo_id:
    # Copiar template
    copia = drive.files().copy(
        fileId=GOOGLE_SHEET_ID,
        body={"name": nombre_archivo, "parents": [carpeta_mes_id]}
    ).execute()
    archivo_id = copia["id"]

# --- Descargar archivo ---
req = drive.files().get_media(fileId=archivo_id)
buf = io.BytesIO()
dl  = MediaIoBaseDownload(buf, req)
done = False
while not done:
    _, done = dl.next_chunk()
buf.seek(0)
wb = openpyxl.load_workbook(buf)
ws = wb.active

# --- Paso 1: Connecteam ---
headers = {"Authorization": f"Bearer {CONNECTEAM_API_KEY}", "Content-Type": "application/json"}
params  = {"startDate": hoy.isoformat(), "endDate": hoy.isoformat()}
turnos   = requests.get("https://api.connecteam.com/shifts/v1/shifts",       headers=headers, params=params).json()
fichajes = requests.get("https://api.connecteam.com/time-clock/v1/time-entries", headers=headers, params=params).json()

# Indexar fichajes por userId+jobId
fichajes_idx = {}
for f in (fichajes if isinstance(fichajes, list) else fichajes.get("data",[])):
    key = (f.get("userId"), f.get("jobId"))
    fichajes_idx[key] = f

# --- Paso 2: Cruzar y completar planilla ---
ausencias = []
tardanzas = []
cubiertos = 0
total     = 0

# Mapear servicios de la planilla a filas
for row in ws.iter_rows(min_row=4):
    servicio = row[2].value  # Col C
    operario = row[3].value  # Col D
    if not servicio or not operario:
        continue
    if str(operario).lower() in IGNORAR:
        continue

    total += 1

    # Buscar turno de este operario/servicio
    turno = next((t for t in (turnos if isinstance(turnos, list) else turnos.get("data",[]))
                  if t.get("jobId","").lower() in str(servicio).lower()), None)

    if not turno:
        row[4].value = "—"  # Col E
        row[5].value = "—"  # Col F
        continue

    fichaje = fichajes_idx.get((turno.get("userId"), turno.get("jobId")))

    if not fichaje:
        row[4].value = "-"
        row[5].value = "NO"
        row[6].value = "No fichó"
        prioridad = "P1" if any(p in str(servicio).lower() for p in P1) else \
                    "P2" if any(p in str(servicio).lower() for p in P2) else "P3"
        row[8].value = prioridad
        ausencias.append({"nombre": operario, "servicio": servicio,
                          "horario": turno.get("scheduledStart",""), "prioridad": prioridad})
    else:
        clock_in = fichaje.get("clockIn")
        sched    = turno.get("scheduledStart","")
        if clock_in and sched:
            fmt = "%Y-%m-%dT%H:%M:%S"
            diff = (datetime.fromisoformat(clock_in[:19]) - datetime.fromisoformat(sched[:19])).total_seconds() / 60
            if diff > 10:
                row[4].value = "X"
                row[5].value = "TARDE"
                row[6].value = datetime.fromisoformat(clock_in[:19]).strftime("%H:%M")
                tardanzas.append({"nombre": operario, "servicio": servicio,
                                  "hora_prog": sched[11:16], "hora_real": clock_in[11:16]})
            else:
                row[4].value = "X"
                row[5].value = "OK"
                cubiertos += 1
        else:
            row[4].value = "X"
            row[5].value = "ACTIVO"
            cubiertos += 1

# --- Subir archivo actualizado ---
buf2 = io.BytesIO()
wb.save(buf2)
buf2.seek(0)
media = MediaIoBaseUpload(buf2, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
drive.files().update(fileId=archivo_id, media_body=media).execute()

# --- Paso 6: Mail ---
hora_actual  = datetime.now().strftime("%H:%M")
fecha_actual = hoy.strftime("%d/%m/%Y")

lineas_aus = "\n".join(
    f"- {a['nombre']} | {a['servicio']} | {a['horario']} | {a['prioridad']}"
    for a in ausencias) or "Ninguna"

lineas_tar = "\n".join(
    f"- {t['nombre']} | {t['servicio']} | {t['hora_prog']} → {t['hora_real']}"
    for t in tardanzas) or "Ninguna"

p1_sin = sum(1 for a in ausencias if a["prioridad"] == "P1")
p2_sin = sum(1 for a in ausencias if a["prioridad"] == "P2")

cuerpo = f"""AUSENCIAS:
{lineas_aus}

TARDANZAS:
{lineas_tar}

RESUMEN:
Cubiertos: {cubiertos} / Total: {total}
P1 sin cubrir: {p1_sin}
P2 sin cubrir: {p2_sin}
"""

msg = MIMEText(cuerpo, "plain", "utf-8")
msg["Subject"] = f"Asistencia {hora_actual} — {fecha_actual}"
msg["From"]    = GMAIL_SENDER
msg["To"]      = GMAIL_RECIPIENT

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
    server.send_message(msg)

print(f"OK — Cubiertos: {cubiertos}/{total}, Ausentes: {len(ausencias)}, Tardanzas: {len(tardanzas)}")
