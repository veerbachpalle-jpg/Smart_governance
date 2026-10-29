import { sampleComplaints } from "./civic-data";
import type { Complaint, NewComplaint, Role, Status, Tokens } from "./civic-types";
export function getIsDemo(): boolean {
  if (typeof window === "undefined") return true;
  const saved = localStorage.getItem("civic-mode");
  if (saved === "demo" || saved === "original") return saved === "demo";
  return import.meta.env["VITE_USE_MOCKS"] === "true" || !import.meta.env["VITE_API_BASE_URL"];
}

export let isDemo = getIsDemo();

export function setDemoMode(value: boolean) {
  isDemo = value;
  if (typeof window !== "undefined") {
    localStorage.setItem("civic-mode", value ? "demo" : "original");
    window.dispatchEvent(new CustomEvent("civic-mode-change", { detail: value }));
  }
}

const base = import.meta.env["VITE_API_BASE_URL"]?.replace(/\/$/, "") ?? "";
const SESSION_KEY = "civic-session";

function readStoredSession(): Tokens | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<Tokens>;
    return value.accessToken && value.refreshToken
      ? {
          accessToken: value.accessToken,
          refreshToken: value.refreshToken,
          role: value.role ?? "citizen",
        }
      : null;
  } catch {
    return null;
  }
}

let tokens: Tokens | null = readStoredSession();
let refreshInFlight: Promise<void> | null = null;
let demoRows = sampleComplaints.map((row) => ({ ...row }));
export class ApiError extends Error {
  constructor(
    message: string,
    public code: number,
  ) {
    super(message);
  }
}

type TokenPayload = Partial<Tokens> & {
  access_token?: string;
  refresh_token?: string;
  role?: Role | "citizen";
};

function decodeJwtPayload(accessToken: string): Record<string, unknown> {
  const encoded = accessToken.split(".")[1];
  if (!encoded) return {};
  const base64 = encoded
    .replaceAll("-", "+")
    .replaceAll("_", "/")
    .padEnd(Math.ceil(encoded.length / 4) * 4, "=");
  return JSON.parse(atob(base64)) as Record<string, unknown>;
}

export function setTokens(value: TokenPayload | null) {
  if (!value) {
    tokens = null;
    if (typeof window !== "undefined") sessionStorage.removeItem(SESSION_KEY);
    return;
  }
  const accessToken = value.accessToken || value.access_token || "";
  const refreshToken = value.refreshToken || value.refresh_token || "";
  let role: Role | "citizen" = value.role || "citizen";
  if (accessToken) {
    try {
      const payload = decodeJwtPayload(accessToken);
      if (payload["role"] === "department_lead") role = "lead";
      else if (typeof payload["role"] === "string") role = payload["role"] as Role | "citizen";
    } catch {
      // fallback
    }
  }
  tokens = { accessToken, refreshToken, role };
  if (typeof window !== "undefined") {
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(tokens));
  }
}

export function getSession() {
  return tokens;
}
async function refreshSession() {
  if (!tokens?.refreshToken)
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  const response = await fetch(`${base}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: tokens.refreshToken, refreshToken: tokens.refreshToken }),
  });
  if (!response.ok) {
    setTokens(null);
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }
  const data = await response.json();
  setTokens(data);
}
export async function request<T>(
  path: string,
  options: RequestInit = {},
  retry = true,
): Promise<T> {
  if (!base)
    throw new ApiError(
      "The municipal service is not connected yet. Please try again once it is available.",
      503,
    );
  const headers = new Headers(options.headers);
  if (!(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (tokens) headers.set("Authorization", `Bearer ${tokens.accessToken}`);
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { ...options, headers });
  } catch {
    throw new ApiError(
      "Connection lost. Your draft is safe. Check your connection and try again.",
      0,
    );
  }
  if (response.status === 401 && retry && tokens) {
    refreshInFlight ??= refreshSession().finally(() => {
      refreshInFlight = null;
    });
    await refreshInFlight;
    return request<T>(path, options, false);
  }
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: "Please sign in to continue.",
      403: "Your role does not have permission for this action.",
      404: "No complaint was found with this tracking ID.",
      409: "This case was updated by someone else. Refresh before continuing.",
      422: "Please check the information and try again.",
      429: "Too many requests. Please wait a moment and retry.",
    };
    throw new ApiError(
      messages[response.status] ?? "The service is temporarily unavailable. Please try again.",
      response.status,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
const delay = () => new Promise<void>((resolve) => setTimeout(resolve, 250));

interface BackendAttachment {
  id: string;
  file_url: string;
  file_name: string;
}

interface BackendComplaint {
  id: string;
  tracking_number: string;
  original_title: string;
  original_description: string;
  original_language: string;
  latitude: number;
  longitude: number;
  address: string;
  ward_name: string | null;
  status: string;
  created_at: string;
  attachments: BackendAttachment[];
}

interface BackendPage<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
  total_count: number;
}

interface PublicTracking {
  tracking_number: string;
  status: string;
  ward_name: string | null;
  created_at: string;
  updated_at: string;
}

function frontendStatus(status: string): Status {
  const normalized = status.toUpperCase();
  if (["CLOSED", "RESOLVED"].includes(normalized)) return "resolved";
  if (["CHALLENGED", "UNDER_REVIEW"].includes(normalized)) return "challenged";
  if (normalized === "REOPENED") return "reopened";
  if (["RESOLUTION_PROPOSED", "CITIZEN_REVIEW"].includes(normalized)) return "review";
  if (["ROUTED", "ACCEPTED_BY_LEAD", "IN_PROGRESS"].includes(normalized)) return "in_progress";
  return "submitted";
}

function inferCategory(text: string): Complaint["category"] {
  const value = text.toLowerCase();
  if (/water|drain|sewer|pipe|flood/.test(value)) return "Water & drainage";
  if (/light|lamp|electric|wire/.test(value)) return "Street lighting";
  if (/waste|garbage|trash|rubbish/.test(value)) return "Waste management";
  if (/danger|safety|manhole|fire|collapse/.test(value)) return "Public safety";
  return "Roads & footpaths";
}

function mediaUrl(path: string): string {
  if (/^https?:\/\//.test(path)) return path;
  try {
    const apiOrigin = new URL(base).origin;
    return `${apiOrigin}${path.startsWith("/") ? path : `/${path}`}`;
  } catch {
    return path;
  }
}

function toComplaint(row: BackendComplaint): Complaint {
  const status = frontendStatus(row.status);
  const date = row.created_at.slice(0, 10);
  return {
    id: row.tracking_number,
    backendId: row.id,
    title: row.original_title,
    description: row.original_description,
    category: inferCategory(`${row.original_title} ${row.original_description}`),
    address: row.address,
    ward: row.ward_name ?? "Ward assignment pending",
    lat: row.latitude,
    lng: row.longitude,
    status,
    date,
    department: status === "submitted" ? "Awaiting human assignment" : "Municipal service team",
    priority: "Normal",
    evidenceVerified: status === "resolved",
    attachments: row.attachments.map((attachment) => mediaUrl(attachment.file_url)),
    activity: [
      {
        title: "Report received",
        note: `Current service status: ${row.status.replaceAll("_", " ").toLowerCase()}.`,
        department: "Citizen services",
        date,
        public: true,
      },
    ],
    language: row.original_language,
  };
}

async function uploadDataUrl(dataUrl: string, index: number): Promise<string> {
  const blob = await fetch(dataUrl).then((response) => response.blob());
  const extension = blob.type === "image/png" ? "png" : blob.type === "image/webp" ? "webp" : "jpg";
  const body = new FormData();
  body.append("file", blob, `complaint-${index + 1}.${extension}`);
  const uploaded = await request<BackendAttachment>("/complaints/attachments/upload", {
    method: "POST",
    body,
  });
  return uploaded.id;
}

export const civicApi = {
  async list(): Promise<Complaint[]> {
    if (!isDemo) {
      if (!tokens) return [];
      const page = await request<BackendPage<BackendComplaint>>("/complaints?limit=100");
      return page.items.map(toComplaint);
    }
    await delay();
    return demoRows;
  },
  async track(identifier: string): Promise<Complaint> {
    if (isDemo) {
      await delay();
      const row = demoRows.find(
        (item) => item.id.toUpperCase() === identifier.trim().toUpperCase(),
      );
      if (!row) throw new ApiError("No complaint was found with this tracking ID.", 404);
      return row;
    }
    const tracked = await request<PublicTracking>(
      `/complaints/${encodeURIComponent(identifier.trim())}/tracking`,
    );
    const date = tracked.created_at.slice(0, 10);
    return {
      id: tracked.tracking_number,
      title: `Complaint ${tracked.tracking_number}`,
      description: "Public tracking view",
      category: "Roads & footpaths",
      address: "Address hidden in public tracking",
      ward: tracked.ward_name ?? "Ward assignment pending",
      lat: 0,
      lng: 0,
      status: frontendStatus(tracked.status),
      date,
      department: tracked.ward_name ?? "Municipal service team",
      priority: "Normal",
      evidenceVerified: ["CLOSED", "RESOLVED"].includes(tracked.status.toUpperCase()),
      attachments: [],
      activity: [
        {
          title: "Latest official status",
          note: `${tracked.status.replaceAll("_", " ").toLowerCase()} · updated ${tracked.updated_at.slice(0, 10)}`,
          department: "Citizen services",
          date: tracked.updated_at.slice(0, 10),
          public: true,
        },
      ],
      language: "en",
    };
  },
  async create(input: NewComplaint, key: string): Promise<Complaint> {
    if (!isDemo) {
      if (!tokens) throw new ApiError("Please sign in before submitting a complaint.", 401);
      const attachmentIds = await Promise.all(input.attachments.map(uploadDataUrl));
      const created = await request<BackendComplaint>("/complaints", {
        method: "POST",
        headers: { "Idempotency-Key": key },
        body: JSON.stringify({
          title: input.title,
          description: input.description,
          original_language: input.language,
          latitude: input.lat,
          longitude: input.lng,
          address: input.address,
          channel: "WEB",
          attachment_ids: attachmentIds,
        }),
      });
      return toComplaint(created);
    }
    await delay();
    const row: Complaint = {
      ...input,
      id: `BLR-2026-${String(1500 + demoRows.length).padStart(5, "0")}`,
      ward: "Ward assignment pending",
      date: new Date().toISOString().slice(0, 10),
      status: "submitted",
      department: "Awaiting assignment",
      priority: "Normal",
      evidenceVerified: false,
      activity: [
        {
          title: "Report received",
          note: "Awaiting human triage and department assignment.",
          department: "Citizen services",
          date: new Date().toISOString().slice(0, 10),
          public: true,
        },
      ],
    };
    demoRows = [row, ...demoRows];
    return row;
  },
  async update(id: string, changes: Partial<Complaint>, action: string): Promise<Complaint> {
    if (!isDemo) {
      const row = await this.list().then((items) => items.find((item) => item.id === id));
      if (!row?.backendId) throw new ApiError("Complaint not found.", 404);
      if (action === "support") {
        await request(`/complaints/${row.backendId}/support`, { method: "POST", body: "{}" });
        return row;
      }
      throw new ApiError(
        "This action is available in the demonstration but is not connected to the municipal API yet.",
        501,
      );
    }
    await delay();
    const row = demoRows.find((item) => item.id === id);
    if (!row) throw new ApiError("Complaint not found.", 404);
    const next = { ...row, ...changes };
    demoRows = demoRows.map((item) => (item.id === id ? next : item));
    return next;
  },
  async transition(
    id: string,
    status: Status,
    note: string,
    isPublic: boolean,
  ): Promise<Complaint> {
    const row = demoRows.find((item) => item.id === id);
    return this.update(
      id,
      {
        status,
        activity: [
          {
            title: note,
            note,
            department: row?.department ?? "Assigned officer",
            date: new Date().toISOString().slice(0, 10),
            public: isPublic,
          },
          ...(row?.activity ?? []),
        ],
      },
      "transition",
    );
  },
};
