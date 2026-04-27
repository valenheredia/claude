const BASE = "https://api.connecteam.com";

async function get(path, params = {}, apiKey) {
  const url = new URL(BASE + path);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const r = await fetch(url, {
    headers: { "X-API-KEY": apiKey, "Content-Type": "application/json" }
  });
  return r.json();
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "*");
  if (req.method === "OPTIONS") return res.status(200).end();

  const apiKey = process.env.CONNECTEAM_API_KEY;

  if (req.method === "GET") {
    return res.json({
      name: "connecteam",
      version: "1.0.0",
      tools: [
        {
          name: "get_shifts_today",
          description: "Turnos programados para hoy",
          inputSchema: { type: "object", properties: {} }
        },
        {
          name: "get_timeclock_today",
          description: "Fichajes del día de hoy",
          inputSchema: { type: "object", properties: {} }
        },
        {
          name: "get_users",
          description: "Lista de empleados",
          inputSchema: { type: "object", properties: {} }
        },
        {
          name: "get_jobs",
          description: "Lista de servicios/jobs",
          inputSchema: { type: "object", properties: {} }
        },
        {
          name: "get_forms",
          description: "Lista de formularios disponibles",
          inputSchema: { type: "object", properties: {} }
        },
        {
          name: "get_form_submissions",
          description: "Respuestas de un formulario. Usar formName con el nombre exacto del formulario.",
          inputSchema: {
            type: "object",
            properties: {
              formName: { type: "string", description: "Nombre del formulario" },
              date: { type: "string", description: "Fecha en formato YYYY-MM-DD. Si no se indica, usa hoy." }
            },
            required: ["formName"]
          }
        }
      ]
    });
  }

  if (req.method === "POST") {
    const { tool, input = {} } = req.body;
    const hoy = new Date(new Date().toLocaleString("en-US", { timeZone: "America/Argentina/Buenos_Aires" }))
      .toISOString().split("T")[0];
    const tzOffset = -3 * 3600;
    const nowUtc = Math.floor(Date.now() / 1000);
    const nowBA = nowUtc + tzOffset;
    const startOfDay = nowBA - (nowBA % 86400);
    const endOfDay = startOfDay + 86399;

    try {
      if (tool === "get_users") {
        const data = await get("/users/v1/users", { limit: 100 }, apiKey);
        return res.json({ result: data?.data?.users || [] });
      }

      if (tool === "get_jobs") {
        let jobs = [], offset = 0;
        while (true) {
          const data = await get("/jobs/v1/jobs", { limit: 50, offset }, apiKey);
          const batch = data?.data?.jobs || [];
          jobs = jobs.concat(batch);
          if (batch.length < 50) break;
          offset += 50;
        }
        return res.json({ result: jobs });
      }

      if (tool === "get_shifts_today") {
        const sched = await get("/scheduler/v1/schedulers", {}, apiKey);
        const schedulerId = sched?.data?.schedulers?.[0]?.schedulerId;
        let shifts = [], offset = 0;
        while (true) {
          const data = await get(
            `/scheduler/v1/schedulers/${schedulerId}/shifts`,
            { startTime: startOfDay, endTime: endOfDay, offset, limit: 50 },
            apiKey
          );
          const batch = data?.data?.shifts || [];
          shifts = shifts.concat(batch);
          if (batch.length < 50) break;
          offset += 50;
        }
        return res.json({ result: shifts });
      }

      if (tool === "get_timeclock_today") {
        const tc = await get("/time-clock/v1/time-clocks", {}, apiKey);
        const tcId = tc?.data?.timeClocks?.[0]?.id;
        const data = await get(
          `/time-clock/v1/time-clocks/${tcId}/time-activities`,
          { startDate: hoy, endDate: hoy },
          apiKey
        );
        return res.json({ result: data?.data?.timeActivitiesByUsers || [] });
      }

      if (tool === "get_forms") {
        const data = await get("/forms/v1/forms", {}, apiKey);
        return res.json({ result: data?.data?.forms || [] });
      }

      if (tool === "get_form_submissions") {
        const { formName, date } = input;
        const targetDate = date || hoy;
        const forms = await get("/forms/v1/forms", {}, apiKey);
        const form = (forms?.data?.forms || []).find(
          f => f.title?.toLowerCase().includes(formName.toLowerCase())
        );
        if (!form) return res.status(404).json({ error: `Formulario "${formName}" no encontrado` });
        const data = await get(
          `/forms/v1/forms/${form.formId}/form_submissions`,
          { startDate: targetDate, endDate: targetDate },
          apiKey
        );
        return res.json({ formId: form.formId, formName: form.title, result: data?.data?.formSubmissions || [] });
      }

      return res.status(400).json({ error: "Tool no reconocida" });

    } catch (e) {
      return res.status(500).json({ error: e.message });
    }
  }
}
