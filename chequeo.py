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

# Obtener lista de schedulers
r_schedulers = requests.get("https://api.connecteam.com/scheduler/v1/schedulers", headers=ct_headers)
print(f"Schedulers status: {r_schedulers.status_code} | Body: {r_schedulers.text[:500]}")
schedulers_data = r_schedulers.json().get("data", {})
schedulers = schedulers_data.get("schedulers", []) if isinstance(schedulers_data, dict) else schedulers_data
if not schedulers:
    raise ValueError("No se encontraron schedulers en Connecteam")
scheduler_id = schedulers[0]["schedulerId"]
print(f"Usando scheduler ID: {scheduler_id}")

# Turnos del día (timestamps Unix)
hoy_ts_start = int(datetime.combine(hoy, datetime.min.time()).timestamp())
hoy_ts_end   = int(datetime.combine(hoy, datetime.max.time()).timestamp())
r_turnos = requests.get(
    f"https://api.connecteam.com/scheduler/v1/schedulers/{scheduler_id}/shifts",
    headers=ct_headers,
    params={"startTime": hoy_ts_start, "endTime": hoy_ts_end}
)
print(f"Turnos status: {r_turnos.status_code} | Body: {r_turnos.text[:300]}")
turnos_raw = r_turnos.json()

# Fichajes del día - primero obtener el time clock ID
r_timeclocks = requests.get("https://api.connecteam.com/time-clock/v1/time-clocks", headers=ct_headers)
print(f"TimeClock status: {r_timeclocks.status_code} | Body: {r_timeclocks.text[:500]}")
timeclocks_data = r_timeclocks.json().get("data", {})
timeclocks = timeclocks_data.get("timeClocks", []) if isinstance(timeclocks_data, dict) else timeclocks_data
if not timeclocks:
    raise ValueError("No se encontraron time clocks en Connecteam")
timeclock_id = timeclocks[0]["id"]
print(f"Usando time clock ID: {timeclock_id}")

r_fichajes = requests.get(
    f"https://api.connecteam.com/time-clock/v1/time-clocks/{timeclock_id}/time-activities",
    headers=ct_headers,
    params={"startDate": hoy.isoformat(), "endDate": hoy.isoformat()}
)
print(f"Fichajes status: {r_fichajes.status_code} | Body: {r_fichajes.text[:300]}")
fichajes_raw = r_fichajes.json()

turnos   = turnos_raw.get("data", {}).get("shifts", [])

# Los fichajes vienen agrupados por usuario
fichajes_por_usuario = {}
for user_data in fichajes_raw.get("data", {}).get("timeActivitiesByUsers", []):
    uid = user_data.get("userId")
    shifts = user_data.get("shifts", [])
    if shifts:
        fichajes_por_usuario[uid] = shifts  # lista de fichajes del día para ese usuario

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
    # Buscar turno que matchee el servicio de la planilla
    turno = next((t for t in turnos if t.get("title","").lower() in str(servicio).lower()
                  or str(servicio).lower() in t.get("title","").lower()), None)

    if not turno:
        row[4].value = "—"
        row[5].value = "—"
        continue

    uid = turno.get("assignedUserIds", [None])[0]
    fichajes_usuario = fichajes_por_usuario.get(uid, [])

    # Buscar fichaje que corresponda al turno (por jobId o por tiempo)
    turno_start = turno.get("startTime", 0)
    fichaje = next((f for f in fichajes_usuario
                    if abs(f.get("start", {}).get("timestamp", 0) - turno_start) < 3600), None)

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
        clock_in_ts = fichaje.get("start", {}).get("timestamp", 0)
        sched_ts    = turno.get("startTime", 0)
        if clock_in_ts and sched_ts:
            diff = (clock_in_ts - sched_ts) / 60
            hora_real = datetime.fromtimestamp(clock_in_ts).strftime("%H:%M")
            hora_prog = datetime.fromtimestamp(sched_ts).strftime("%H:%M")
            if diff > 10:
                row[4].value = "X"
                row[5].value = "TARDE"
                row[6].value = hora_real
                tardanzas.append({"nombre": operario, "servicio": servicio,
                                  "hora_prog": hora_prog, "hora_real": hora_real})
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
