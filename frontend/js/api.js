/* ============================================================
   api.js — Cliente HTTP de la API REST.
   Todas las peticiones envían/usan la cookie de sesión.
   ============================================================ */
const API = (() => {
  async function request(method, url, body, isForm = false) {
    const opts = { method, credentials: "same-origin", headers: {} };
    if (body !== undefined) {
      if (isForm) {
        opts.body = body; // FormData
      } else {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
    }
    const res = await fetch(url, opts);
    if (!res.ok) {
      let detail = `Error ${res.status}`;
      try {
        const data = await res.json();
        detail = data.detail || detail;
      } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  }

  return {
    get: (url) => request("GET", url),
    post: (url, body) => request("POST", url, body),
    put: (url, body) => request("PUT", url, body),

    session: () => request("GET", "/api/session"),

    upload: (file) => {
      const fd = new FormData();
      fd.append("file", file);
      return request("POST", "/api/upload", fd, true);
    },

    dashboard: () => request("GET", "/api/dashboard"),

    getWeights: () => request("GET", "/api/weights"),
    putWeights: (rows) => request("PUT", "/api/weights", { rows }),
    saveWeights: () => request("POST", "/api/weights/save"),
    restoreWeights: () => request("POST", "/api/weights/restore"),
    autoA: (eventos, decimales) => request("POST", "/api/weights/auto-a", { eventos, decimales }),
    defaultBudget: (eventos) => request("POST", "/api/weights/default-budget", { eventos }),
    equalize: (eventos, presupuesto_total) => request("POST", "/api/weights/equalize", { eventos, presupuesto_total }),
    jointAdjust: (eventos, presupuesto_total, decimales) =>
      request("POST", "/api/weights/joint-adjust", { eventos, presupuesto_total, decimales }),

    getRetention: () => request("GET", "/api/retention"),
    putRetention: (rows) => request("PUT", "/api/retention", { rows }),
    saveRetention: () => request("POST", "/api/retention/save"),
    resetRetention: () => request("POST", "/api/retention/reset"),
    templateRetention: () => request("POST", "/api/retention/template"),

    events: () => request("GET", "/api/events"),
    eventAnalysis: (event) => request("GET", `/api/events/analysis?event=${encodeURIComponent(event)}`),

    process: (payload) => request("POST", "/api/process", payload),
    exportUrl: (kind, params) => {
      const qs = params ? new URLSearchParams(params).toString() : "";
      return `/api/export/${kind}${qs ? `?${qs}` : ""}`;
    },

    chequesPreview: (file) => {
      const fd = new FormData();
      fd.append("file", file);
      return request("POST", "/api/cheques/preview", fd, true);
    },
    chequesPdf: async (file, fecha, serie, calibration, incluirDorso) => {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("fecha", fecha);
      if (serie) fd.append("serie_inicial", serie);
      if (calibration) fd.append("calibration", JSON.stringify(calibration));
      fd.append("incluir_dorso", incluirDorso ? "true" : "false");
      const res = await fetch("/api/cheques/pdf", { method: "POST", body: fd, credentials: "same-origin" });
      if (!res.ok) {
        let detail = `Error ${res.status}`;
        try { detail = (await res.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      return res.blob();
    },
    chequesCalibDefaults: () => request("GET", "/api/cheques/calibration-defaults"),
    chequesEjemplo: async (payload) => {
      const res = await fetch("/api/cheques/ejemplo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload || {}),
        credentials: "same-origin",
      });
      if (!res.ok) {
        let detail = `Error ${res.status}`;
        try { detail = (await res.json()).detail || detail; } catch (_) {}
        throw new Error(detail);
      }
      return res.blob();
    },
    chequesCalibPdf: async (calibration, incluirDorso) => {
      const body = { ...(calibration || {}), incluir_dorso: !!incluirDorso };
      const res = await fetch("/api/cheques/calibracion", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        credentials: "same-origin",
      });
      if (!res.ok) throw new Error(`Error ${res.status}`);
      return res.blob();
    },
  };
})();
