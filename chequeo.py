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
TEMPLATE_ID        = os.environ["GOOGLE_SHEET_ID"]     # ID del template xlsx
REGISTRO_ID        = "1duUISVaQ4Lk9djwpOGXY88_jjSVsKn6N"  # Carpeta Registro checklist
GMAIL_SENDER       = os.environ["GMAIL_SENDER"]
GMAIL_RECIPIENT    = os.environ["GMAIL_RECIPIENT"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]
SA_JSON            = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
 
MESES_ES = {
    1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",
    7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"
}
P1      = ["bilder","vonderk","esparza","correa","triunvirato 5375"]
P2      = ["amenábar 3208","ciudad de la paz","core oficina","conesa 2958","vonderk depósito"]
IGNORAR = ["walter benitez","rodrigo martinez"]
 
# --- Auth ---
creds = Credentials.from_service_account_info(
    json.loads(SA_JSON),
    scopes=["https://www.googleapis.com/auth/drive"]
)
drive = build("drive", "v3", credentials=creds)
 
hoy            = date.today()
nombre_archivo = hoy.strftime("%d/%m/%Y") + ".xlsx"
nombre_carpeta = f"{MESES_ES[hoy.month]} {hoy.year}"
 
DRIVE_OPTS = dict(supportsAllDrives=True, includeItemsFromAllDrives=True)
 
def buscar_id(nombre, tipo, parent):
    q = f"name='{nombre}' and mimeType='{tipo}' and '{parent}' in parents and trashed=false"
    r = drive.files().list(q=q, fields="files(id)", **DRIVE_OPTS).execute()
    files = r.get("files", [])
    return files[0]["id"] if files else None
 
# --- Buscar o crear carpeta del mes ---
carpeta_mes_id = buscar_id(nombre_carpeta, "application/vnd.google-apps.folder", REGISTRO_ID)
if not carpeta_mes_id:
    meta = {"name": nombre_carpeta, "mimeType": "application/vnd.google-apps.folder",
            "parents": [REGISTRO_ID]}
    carpeta_mes_id = drive.files().create(body=meta, fields="id", **DRIVE_OPTS).execute()["id"]
    print(f"Carpeta creada: {nombre_carpeta}")
 
# --- Buscar o crear archivo del día ---
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
archivo_id = buscar_id(nombre_archivo, MIME_XLSX, carpeta_mes_id)
 
if not archivo_id:
    # Exportar Google Sheet template como xlsx
    req = drive.files().export_media(
        fileId=TEMPLATE_ID,
        mimeType=MIME_XLSX
    )
    buf_t = io.BytesIO()
    dl = MediaIoBaseDownload(buf_t, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    buf_t.seek(0)
    # Subir como archivo del día en la carpeta del mes
    media = MediaIoBaseUpload(buf_t, mimetype=MIME_XLSX)
    archivo_id = drive.files().create(
        body={"name": nombre_archivo, "parents": [carpeta_mes_id]},
        media_body=media, fields="id", **DRIVE_OPTS
    ).execute()["id"]
    print(f"Archivo creado: {nombre_archivo}")
 
# --- Descargar archivo del día ---
req = drive.files().get_media(fileId=archivo_id, **DRIVE_OPTS)
buf = io.BytesIO()
dl  = MediaIoBaseDownload(buf, req)
done = False
while not done:
    _, done = dl.next_chunk()
buf.seek(0)
wb = openpyxl.load_workbook(buf)
ws = wb.active
 
# --- Connecteam ---
ct_headers = {"Authorization": f"Bearer {CONNECTEAM_API_KEY}", "Content-Type": "application/json"}
ct_params  = {"startDate": hoy.isoformat(), "endDate": hoy.isoformat()}
turnos_raw   = requests.get("https://api.connecteam.com/shifts/v1/shifts", headers=ct_headers, params=ct_params).json()
fichajes_raw = requests.get("https://api.connecteam.com/time-clock/v1/time-entries", headers=ct_headers, params=ct_params).json()
 
turnos   = turnos_raw   if isinstance(turnos_raw,   list) else turnos_raw.get("data",   [])
fichajes = fichajes_raw if isinstance(fichajes_raw, list) else fichajes_raw.get("data", [])
 
fichajes_idx = {}
for f in fichajes:
    key = (f.get("userId"), f.get("jobId"))
    fichajes_idx[key] = f
 
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
drive.files().update(fileId=archivo_id, media_body=media2, **DRIVE_OPTS).execute()
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
