export const config = { runtime: "edge" };

const TOOLS = [
  { name: "get_shifts_today", description: "Turnos programados para hoy", inputSchema: { type: "object", properties: {} } },
  { name: "get_timeclock_today", description: "Fichajes del día", inputSchema: { type: "object", properties: {} } },
  { name: "get_users", description: "Lista de empleados", inputSchema: { type: "object", properties: {} } },
  { name: "get_jobs", description: "Lista de servicios/jobs", inputSchema: { type: "object", properties: {} } },
  { name: "get_forms", description: "Lista de formularios", inputSchema: { type: "object", properties: {} } },
  {
    name: "get_form_submissions",
    description: "Respuestas de un formulario por nombre",
    inputSchema: {
      type: "object",
      properties: {
        formName: { type: "string" },
        date: { type: "string", description: "YYYY-MM-DD, default hoy" }
      },
      required: ["formName"]
    }
  }
];

async function callConnecteam(path, params = {}, apiKey) {
  const url = new URL("https://api.connecteam.com" + path);
  Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
  const r = await fetch(url, { headers: { "X-API-KEY": apiKey } });
  return r.json();
}

async function handleTool(tool, input, apiKey) {
  const hoy = new Date(new Date().toLocaleString("en-US", { timeZone: "America/Argentina/Buenos_Aires" }))
    .toISOString().split("T")[0];
  const nowBA = Math.floor(Date.now() / 1000) - 3 * 3600;
  const startOfDay = nowBA - (nowBA % 86400);
  const endOfDay = startOfDay + 86399;

  if (tool === "get_users") {
    const d = await callConnecteam("/users/v1/users", { limit: 100 }, apiKey);
    return d?.data?.users || [];
  }
  if (tool === "get_jobs") {
    let jobs = [], offset = 0;
    while (true) {
      const d = await callConnecteam("/jobs/v1/jobs", { limit: 50, offset }, apiKey);
      const batch = d?.data?.jobs || [];
      jobs = jobs.concat(batch);
      if (batch.length < 50) break;
      offset += 50;
    }
    return jobs;
  }
  if (tool === "get_shifts_today") {
    const s = await callConnecteam("/scheduler/v1/schedulers", {}, apiKey);
    const sid = s?.data?.schedulers?.[0]?.schedulerId;
    let shifts = [], offset = 0;
    while (true) {
      const d = await callConnecteam(`/scheduler/v1/schedulers/${sid}/shifts`,
        { startTime: startOfDay, endTime: endOfDay, offset, limit: 50 }, apiKey);
      const batch = d?.data?.shifts || [];
      shifts = shifts.concat(batch);
      if (batch.length < 50) break;
      offset += 50;
    }
    return shifts;
  }
  if (tool === "get_timeclock_today") {
    const tc = await callConnecteam("/time-clock/v1/time-clocks", {}, apiKey);
    const tcId = tc?.data?.timeClocks?.[0]?.id;
    const d = await callConnecteam(`/time-clock/v1/time-clocks/${tcId}/time-activities`,
      { startDate: hoy, endDate: hoy }, apiKey);
    return d?.data?.timeActivitiesByUsers || [];
  }
  if (tool === "get_forms") {
    const d = await callConnecteam("/forms/v1/forms", {}, apiKey);
    return d?.data?.forms || [];
  }
  if (tool === "get_form_submissions") {
    const { formName, date } = input;
    const targetDate = date || hoy;
    const forms = await callConnecteam("/forms/v1/forms", {}, apiKey);
    const form = (forms?.data?.forms || []).find(
      f => f.title?.toLowerCase().includes(formName.toLowerCase())
    );
    if (!form) throw new Error(`Formulario "${formName}" no encontrado`);
    const d = await callConnecteam(`/forms/v1/forms/${form.formId}/form_submissions`,
      { startDate: targetDate, endDate: targetDate }, apiKey);
    return { formId: form.formId, formName: form.title, submissions: d?.data?.formSubmissions || [] };
  }
  throw new Error(`Tool desconocida: ${tool}`);
}

export default async function handler(req) {
  const apiKey = process.env.CONNECTEAM_API_KEY;
  const headers = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "*",
  };

  if (req.method === "OPTIONS") return new Response(null, { status: 200, headers });

  // SSE endpoint — Claude connects here first
  if (req.method === "GET") {
    const { readable, writable } = new TransformStream();
    const writer = writable.getWriter();
    const encoder = new TextEncoder();

    const send = (data) => writer.write(encoder.encode(`data: ${JSON.stringify(data)}\n\n`));

    (async () => {
      await send({
        jsonrpc: "2.0",
        method: "notifications/initialized",
        params: {}
      });
      // Keep alive
      const interval = setInterval(async () => {
        try { await writer.write(encoder.encode(": ping\n\n")); }
        catch { clearInterval(interval); }
      }, 15000);
    })();

    return new Response(readable, {
      headers: {
        ...headers,
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
      }
    });
  }

  // POST — handle MCP messages
  if (req.method === "POST") {
    const body = await req.json();
    const { method, params, id } = body;

    const respond = (result) => new Response(
      JSON.stringify({ jsonrpc: "2.0", id, result }),
      { headers: { ...headers, "Content-Type": "application/json" } }
    );
    const error = (code, message) => new Response(
      JSON.stringify({ jsonrpc: "2.0", id, error: { code, message } }),
      { headers: { ...headers, "Content-Type": "application/json" } }
    );

    if (method === "initialize") {
      return respond({
        protocolVersion: "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "connecteam", version: "1.0.0" }
      });
    }

    if (method === "notifications/initialized") return new Response(null, { status: 200, headers });

    if (method === "tools/list") return respond({ tools: TOOLS });

    if (method === "tools/call") {
      try {
        const result = await handleTool(params?.name, params?.arguments || {}, apiKey);
        return respond({ content: [{ type: "text", text: JSON.stringify(result) }] });
      } catch (e) {
        return error(-32000, e.message);
      }
    }

    return error(-32601, "Method not found");
  }

  return new Response("Not found", { status: 404, headers });
}
