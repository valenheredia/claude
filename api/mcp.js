export default async function handler(req, res) {
  const apiKey = process.env.CONNECTEAM_API_KEY;
  const BASE = "https://api.connecteam.com";

  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "*");
  if (req.method === "OPTIONS") return res.status(200).end();

  async function get(path, params = {}) {
    const url = new URL(BASE + path);
    Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const r = await fetch(url, {
      headers: { "X-API-KEY": apiKey, "Content-Type": "application/json" }
    });
    return r.json();
  }

  // MCP Protocol handler
  if (req.method === "POST") {
    const body = req.body;
    const { method, params, id } = body;

    // MCP initialize
    if (method === "initialize") {
      return res.json({
        jsonrpc: "2.0", id,
        result: {
          protocolVersion: "2024-11-05",
          capabilities: { tools: {} },
          serverInfo: { name: "connecteam", version: "1.0.0" }
        }
      });
    }

    // MCP tools/list
    if (method === "tools/list") {
      return res.json({
        jsonrpc: "2.0", id,
        result: {
          tools: [
            { name: "get_shifts_today", description: "Turnos programados para hoy", inputSchema: { type: "object", properties: {} } },
            { name: "get_timeclock_today", description: "Fichajes del día", inputSchema: { type: "object", properties: {} } },
            { name: "get_users", description: "Lista de empleados", inputSchema: { type: "object", properties: {} } },
            { name: "get_jobs", description: "Lista de servicios/jobs", inputSchema: { type: "object", properties: {} } },
            { name: "get_forms", description: "Lista de formularios", inputSchema: { type: "object", properties: {} } },
            {
              name: "get_form_submissions",
              description: "Respuestas de un formulario por nombre y fecha",
              inputSchema: {
                type: "object",
                properties: {
                  formName: { type: "string" },
                  date: { type: "string", description: "YYYY-MM-DD, default hoy" }
                },
                required: ["formName"]
              }
            }
          ]
        }
      });
    }

    // MCP tools/call
    if (method === "tools/call") {
      const tool = params?.name;
      const input = params?.arguments || {};

      const hoy = new Date(new Date().toLocaleString("en-US", { timeZone: "America/Argentina/Buenos_Aires" }))
        .toISOString().split("T")[0];
      const nowUtc = Math.floor(Date.now() / 1000);
      const nowBA = nowUtc + (-3 * 3600);
      const startOfDay = nowBA - (nowBA % 86400);
      const endOfDay = startOfDay + 86399;

      try {
        let result;

        if (tool === "get_users") {
          const data = await get("/users/v1/users", { limit: 100 });
          result = data?.data?.users || [];
        }
        else if (tool === "get_jobs") {
          let jobs = [], offset = 0;
          while (true) {
            const data = await get("/jobs/v1/jobs", { limit: 50, offset });
            const batch = data?.data?.jobs || [];
            jobs = jobs.concat(batch);
            if (batch.length < 50) break;
            offset += 50;
          }
          result = jobs;
        }
        else if (tool === "get_shifts_today") {
          const sched = await get("/scheduler/v1/schedulers");
          const schedulerId = sched?.data?.schedulers?.[0]?.schedulerId;
          let shifts = [], offset = 0;
          while (true) {
            const data = await get(`/scheduler/v1/schedulers/${schedulerId}/shifts`,
              { startTime: startOfDay, endTime: endOfDay, offset, limit: 50 });
            const batch = data?.data?.shifts || [];
            shifts = shifts.concat(batch);
            if (batch.length < 50) break;
            offset += 50;
          }
          result = shifts;
        }
        else if (tool === "get_timeclock_today") {
          const tc = await get("/time-clock/v1/time-clocks");
          const tcId = tc?.data?.timeClocks?.[0]?.id;
          const data = await get(`/time-clock/v1/time-clocks/${tcId}/time-activities`,
            { startDate: hoy, endDate: hoy });
          result = data?.data?.timeActivitiesByUsers || [];
        }
        else if (tool === "get_forms") {
          const data = await get("/forms/v1/forms");
          result = data?.data?.forms || [];
        }
        else if (tool === "get_form_submissions") {
          const { formName, date } = input;
          const targetDate = date || hoy;
          const forms = await get("/forms/v1/forms");
          const form = (forms?.data?.forms || []).find(
            f => f.title?.toLowerCase().includes(formName.toLowerCase())
          );
          if (!form) throw new Error(`Formulario "${formName}" no encontrado`);
          const data = await get(`/forms/v1/forms/${form.formId}/form_submissions`,
            { startDate: targetDate, endDate: targetDate });
          result = { formId: form.formId, formName: form.title, submissions: data?.data?.formSubmissions || [] };
        }
        else {
          throw new Error(`Tool desconocida: ${tool}`);
        }

        return res.json({
          jsonrpc: "2.0", id,
          result: { content: [{ type: "text", text: JSON.stringify(result) }] }
        });

      } catch (e) {
        return res.json({
          jsonrpc: "2.0", id,
          error: { code: -32000, message: e.message }
        });
      }
    }

    // notifications/initialized — no response needed
    if (method === "notifications/initialized") {
      return res.status(200).end();
    }

    return res.json({ jsonrpc: "2.0", id, error: { code: -32601, message: "Method not found" } });
  }

  return res.status(405).end();
}
