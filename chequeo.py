import os, requests, smtplib, io
from datetime import date, datetime
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2.service_account import Credentials
import openpyxl
import json

# --- Credenciales ---
CONNECTEAM_API_KEY = os.environ["CONNECTEAM_API_KEY"]
GMAIL_SENDER       = os.environ["GMAIL_SENDER"]
GMAIL_RECIPIENT    = os.environ["GMAIL_RECIPIENT"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
SA_JSON            = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]

REGISTRO_ID = "1duUISVaQ4Lk9djwpOGXY88_jjSVsKn6N"  # Carpeta Registro checklist

MESES_ES = {
    1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
    7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"
}
P1      = ["bilder","vonderk","esparza","correa","triunvirato 5375"]
P2      = ["amenábar 3208","ciudad de la paz","core oficina","conesa 2958","vonderk depósito"]
IGNORAR = ["walter benitez","rodrigo martinez"]

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DRIVE_OPTS = dict(supportsAllDrives=True, includeItemsFromAllDrives=True)

# --- Auth ---
creds = Credentials.from_service_account_info(
    json.loads(SA_JSON),
    scopes=["https://www.googleapis.com/auth/drive"]
)
drive = build("drive", "v3", credentials=creds)

hoy            = date.today()
nombre_archivo = hoy.strftime("%d/%m/%Y") + ".xlsx"
nombre_carpeta = f"{MESES_ES[hoy.month]} {hoy.year}"

# --- Buscar carpeta del mes ---
q = f"name='{nombre_carpeta}' and mimeType='application/vnd.google-apps.folder' and '{REGISTRO_ID}' in parents and trashed=false"
r = drive.files().list(q=q, fields="files(id)", **DRIVE_OPTS).execute()
files = r.get("files", [])
if not files:
    raise FileNotFoundError(f"No existe la carpeta '{nombre_carpeta}' en Registro checklist. Creala antes de que corra el script.")
carpeta_mes_id = files[0]["id"]

# --- Buscar archivo del día ---
q2 = f"name='{nombre_archivo}' and '{carpeta_mes_id}' in parents and trashed=false"
r2 = drive.files().list(q=q2, fields="files(id)", **DRIVE_OPTS).execute()
files2 = r2.get("files", [])
if not files2:
    raise FileNotFoundError(f"No existe el archivo '{nombre_archivo}' en '{nombre_carpeta}'. Crealo antes de que corra el script.")
archivo_id = files2[0]["id"]
print(f"Archivo encontrado: {nombre_archivo}")

# --- Descargar archivo del día ---
req = drive.files().get_media(fileId=archivo_id, supportsAllDrives=True)
buf = io.BytesIO()
dl  = MediaIoBaseDownload(buf, req)
done = False
while not done:
    _, done = dl.next_chunk()
buf.seek(0)
wb = openpyxl.load_workbook(buf)
ws = wb.active

# --- Connecteam ---
ct_headers = {"X-API-KEY": CONNECTEAM_API_KEY, "Content-Type": "application/json"}
ct_params  = {"startDate": hoy.isoformat(), "endDate": hoy.isoformat()}
r_me = requests.get("https://api.connecteam.com/me", headers=ct_headers)
print(f"ME status: {r_me.status_code} | Body: {r_me.text[:300]}")

r_turnos = requests.get("https://api.connecteam.com/shifts/v1/shifts", headers=ct_headers, params=ct_params)
print(f"Turnos status: {r_turnos.status_code} | Body: {r_turnos.text[:300]}")
turnos_raw = r_turnos.json()
r_fichajes = requests.get("https://api.connecteam.com/time-clock/v1/time-entries", headers=ct_headers, params=ct_params)
print(f"Fichajes status: {r_fichajes.status_code} | Body: {r_fichajes.text[:300]}")
fichajes_raw = r_fichajes.json()

turnos   = turnos_raw   if isinstance(turnos_raw,   list) else turnos_raw.get("data",   [])
fichajes = fichajes_raw if isinstance(fichajes_raw, list) else fichajes_raw.get("data", [])

fichajes_idx = {}
for f in fichajes:
    fichajes_idx[(f.get("userId"), f.get("jobId"))] = f

# --- Cruzar y completar ---
ausencias, tardanzas = [], []
cubiertos, total = 0, 0

for row in ws.iter_rows(min_row=4):
    servicio = row[2].value  # Col C
    operario = row[3].value  # Col D
    if not servicio or not operario:
        continue
    if str(operario).strip().lower() in IGNORAR:
        continue
    if row[4].value:  # Col E ya completada — no sobreescribir
        continue

    total += 1
    turno = next((t for t in turnos if t.get("jobId","").lower() in str(servicio).lower()), None)

    if not turno:
        row[4].value = "—"
        row[5].value = "—"
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
                          "horario": turno.get("scheduledStart","")[11:16], "prioridad": prioridad})
    else:
        clock_in = fichaje.get("clockIn","")
        sched    = turno.get("scheduledStart","")
        if clock_in and sched:
            diff = (datetime.fromisoformat(clock_in[:19]) - datetime.fromisoformat(sched[:19])).total_seconds() / 60
            if diff > 10:
                row[4].value = "X"
                row[5].value = "TARDE"
                row[6].value = clock_in[11:16]
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
media2 = MediaIoBaseUpload(buf2, mimetype=MIME_XLSX)
drive.files().update(fileId=archivo_id, media_body=media2, supportsAllDrives=True).execute()
print("Planilla actualizada en Drive")

# --- Mail ---
hora_actual  = datetime.now().strftime("%H:%M")
fecha_actual = hoy.strftime("%d/%m/%Y")

lineas_aus = "\n".join(
    f"- {a['nombre']} | {a['servicio']} | {a['horario']} | {a['prioridad']}"
    for a in ausencias) or "Ninguna"

lineas_tar = "\n".join(
    f"- {t['nombre']} | {t['servicio']} | {t['hora_prog']} → {t['hora_real']}"
    for t in tardanzas) or "Ninguna"

cuerpo = f"""AUSENCIAS:
{lineas_aus}

TARDANZAS:
{lineas_tar}

RESUMEN:
Cubiertos: {cubiertos} / Total: {total}
P1 sin cubrir: {sum(1 for a in ausencias if a['prioridad']=='P1')}
P2 sin cubrir: {sum(1 for a in ausencias if a['prioridad']=='P2')}
"""

msg = MIMEText(cuerpo, "plain", "utf-8")
msg["Subject"] = f"Asistencia {hora_actual} — {fecha_actual}"
msg["From"]    = GMAIL_SENDER
msg["To"]      = GMAIL_RECIPIENT

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
    server.send_message(msg)

print(f"OK — Cubiertos: {cubiertos}/{total}, Ausentes: {len(ausencias)}, Tardanzas: {len(tardanzas)}")
