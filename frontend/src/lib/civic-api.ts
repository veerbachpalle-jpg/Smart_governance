import { sampleComplaints } from "./civic-data";
import type { Complaint, NewComplaint, Role, Status, Tokens, TrendingIssue } from "./civic-types";
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

function getResolvedApiBase(): string {
  const envUrl = import.meta.env["VITE_API_BASE_URL"];
  let raw = (envUrl || "https://smart-governance-ai-synergy-api.onrender.com/api/v1").trim().replace(/\/+$/, "");
  if (raw.includes("smart-governance-ai-synergy-api-1onx.onrender.com")) {
    raw = raw.replace("smart-governance-ai-synergy-api-1onx.onrender.com", "smart-governance-ai-synergy-api.onrender.com");
  }
  if (!raw.endsWith("/api/v1")) {
    raw = `${raw}/api/v1`;
  }
  return raw;
}
const base = getResolvedApiBase();
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
  const currentLang = typeof window !== "undefined" ? (localStorage.getItem("civic-language") || "en") : "en";
  headers.set("Accept-Language", currentLang);
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { ...options, headers });
  } catch (fetchErr) {
    console.error("Municipal API request failed:", fetchErr, "Target URL:", `${base}${path}`);
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
    let serverDetail: string | undefined;
    try {
      const errJson = await response.json();
      serverDetail = errJson.detail || errJson.message;
    } catch {
      // ignore
    }
    const messages: Record<number, string> = {
      401: serverDetail || "Invalid credentials. Please check your phone/email and password.",
      403: "Your role does not have permission for this action.",
      404: "No complaint was found with this tracking ID.",
      409: "This case was updated by someone else. Refresh before continuing.",
      422: serverDetail || "Please check the information and try again.",
      429: "Too many requests. Please wait a moment and retry.",
    };
    throw new ApiError(
      (serverDetail || messages[response.status]) ?? "The service is temporarily unavailable. Please try again.",
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
  upvote_count: number;
  priority_band: string;
  composite_score: number;
  sla_deadline: string | null;
  sla_seconds_remaining: number | null;
  is_sla_overdue: boolean;
  department_name: string | null;
  department_id: string | null;
  ward_number: number | null;
}

export interface MunicipalDepartment {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_active: boolean;
}

interface BackendTrendingIssue {
  id: string;
  tracking_number: string;
  title: string;
  latitude: number;
  longitude: number;
  ward_name: string | null;
  ward_number: number | null;
  status: string;
  distance_meters: number;
  upvote_count: number;
  priority_band: string;
  composite_score: number;
  upvoted_by_current_user: boolean;
}

interface BackendUpvoteResult {
  complaint_id: string;
  upvote_count: number;
  upvoted: boolean;
  message: string;
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
  if (/drain|sewer|flood|overflow|gutter/.test(value)) return "Stormwater & drainage";
  if (/water|pipeline|leak|drinking|tap/.test(value)) return "Water supply";
  if (/light|lamp|electric|wire|pole|bulb|power/.test(value)) return "Street lighting";
  if (/waste|garbage|trash|rubbish|dump|bin|sweep/.test(value)) return "Waste management";
  if (/park|tree|branch|garden|horticult|grass/.test(value)) return "Parks & horticulture";
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
    department:
      row.department_name ??
      (status === "submitted" ? "Awaiting human assignment" : "Municipal service team"),
    ...(row.department_id ? { departmentId: row.department_id } : {}),
    priority:
      row.priority_band === "CRITICAL"
        ? "Critical"
        : row.priority_band === "HIGH"
          ? "High"
          : "Normal",
    priorityBand: (["LOW", "MEDIUM", "HIGH", "CRITICAL"].includes(row.priority_band)
      ? row.priority_band
      : "MEDIUM") as NonNullable<Complaint["priorityBand"]>,
    upvoteCount: row.upvote_count ?? 0,
    compositeScore: row.composite_score ?? 0,
    ...(row.sla_deadline ? { slaDeadline: row.sla_deadline } : {}),
    ...(row.sla_seconds_remaining !== null
      ? { slaSecondsRemaining: row.sla_seconds_remaining }
      : {}),
    slaOverdue: row.is_sla_overdue ?? false,
    ...(row.ward_number !== null ? { wardNumber: row.ward_number } : {}),
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

async function resolveCaseIdForComplaint(complaintBackendId: string): Promise<string> {
  try {
    const casesResp = await request<{ items: Array<{ id: string; complaint_ids: string[] }> }>("/cases?limit=100");
    const matched = casesResp.items.find((c) => c.complaint_ids.includes(complaintBackendId));
    if (matched) return matched.id;
  } catch {
    // ignore
  }
  return complaintBackendId;
}

export const civicApi = {
  async departments(): Promise<MunicipalDepartment[]> {
    if (isDemo) {
      return [];
    }
    return request<MunicipalDepartment[]>("/users/departments");
  },
  async decideTriage(
    complaint: Complaint,
    recommendation: "Department routing" | "Priority",
    decision: "Accept" | "Override" | "Reject",
    reason: string,
    overrideValue?: string,
  ): Promise<void> {
    if (isDemo) {
      // Simulate triage decision in demo mode by updating demoRows
      const index = demoRows.findIndex((r) => r.id === complaint.id);
      if (index !== -1) {
        const updated = { ...demoRows[index] } as any;
        if (recommendation === "Department routing") {
          updated.department = overrideValue || complaint.department;
          updated.departmentConfirmed = true;
        } else {
          const mappedPriority = overrideValue === "CRITICAL" ? "Critical" : overrideValue === "HIGH" ? "High" : "Normal";
          updated.priority = mappedPriority;
          updated.priorityBand = (overrideValue as any) || "MEDIUM";
          updated.priorityConfirmed = true;
        }
        updated.status = decision === "Reject" ? "rejected" : "in_progress";
        const newAct = {
          title: `${recommendation} ${decision}`,
          note: reason || `Triage decision recorded by municipal officer: ${decision} (${overrideValue || complaint.department || complaint.priority}).`,
          department: updated.department,
          date: new Date().toISOString().slice(0, 10),
          public: false,
        };
        updated.activity = [newAct, ...(updated.activity || [])];
        demoRows.splice(index, 1, updated);
      }
      return;
    }

    if (!complaint.backendId) throw new ApiError("Complaint not found.", 404);
    const decisionPath = decision.toLowerCase();
    if (recommendation === "Department routing") {
      const body =
        decision === "Accept"
          ? { notes: reason || undefined }
          : decision === "Override"
            ? { department_id: overrideValue, reason }
            : { reason };
      await request(`/complaints/${complaint.backendId}/routing/${decisionPath}`, {
        method: "POST",
        body: JSON.stringify(body),
      });
      return;
    }
    const body =
      decision === "Accept"
        ? { notes: reason || undefined }
        : decision === "Override"
          ? { priority: overrideValue, reason }
          : { reason };
    await request(`/complaints/${complaint.backendId}/priority/${decisionPath}`, {
      method: "POST",
      body: JSON.stringify(body),
    });
  },
  async submitManualTriage(
    complaint: Complaint,
    input: { departmentId: string; priority: "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"; notes: string },
  ): Promise<void> {
    if (isDemo) return;
    if (!complaint.backendId) throw new ApiError("Complaint not found.", 404);
    await request(`/triage/manual/${complaint.backendId}`, {
      method: "POST",
      body: JSON.stringify({
        category: complaint.category,
        department_id: input.departmentId,
        priority: input.priority,
        notes: input.notes,
      }),
    });
  },
  async list(): Promise<Complaint[]> {
    if (!isDemo) {
      if (!tokens) return [];
      const page = await request<BackendPage<BackendComplaint>>("/complaints?limit=100");
      let caseMap: Record<string, string> = {};
      try {
        const casesResp = await request<{ items: Array<{ id: string; complaint_ids: string[] }> }>("/cases?limit=100");
        for (const c of casesResp.items) {
          for (const cid of c.complaint_ids) {
            caseMap[cid] = c.id;
          }
        }
      } catch {
        // non-staff
      }
      return page.items.map((item) => {
        const c = toComplaint(item);
        const mappedCaseId = caseMap[item.id];
        if (mappedCaseId) c.caseId = mappedCaseId;
        return c;
      });
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
      priorityBand: "MEDIUM",
      upvoteCount: 0,
      compositeScore: 10_000,
      slaOverdue: false,
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
  async update(id: string, changes: Partial<Complaint> & { note?: string }, action: string): Promise<Complaint> {
    if (!isDemo) {
      const row = await this.list().then((items) => items.find((item) => item.id === id));
      if (!row?.backendId) throw new ApiError("Complaint not found.", 404);
      const caseId = row.caseId || (await resolveCaseIdForComplaint(row.backendId));
      switch (action) {
        case "support":
          await request(`/complaints/${row.backendId}/support`, { method: "POST", body: "{}" });
          break;
        case "confirm": {
          const feedbackText = (changes as any)?.note || "Resolution verified and confirmed";
          try {
            await request(`/complaints/${row.backendId}/confirm`, {
              method: "POST",
              body: JSON.stringify({ feedback: feedbackText }),
            });
          } catch {
            await request(`/cases/${caseId}/confirm`, {
              method: "POST",
              body: JSON.stringify({ feedback: feedbackText }),
            });
          }
          break;
        }
        case "challenge": {
          const reason = (changes as any)?.challenge?.reason || "Citizen contested resolution";
          try {
            await request(`/complaints/${row.backendId}/challenge`, {
              method: "POST",
              body: JSON.stringify({
                challenge_type: "RESOLUTION",
                reason,
                attachment_ids: [],
              }),
            });
          } catch {
            await request(`/cases/${caseId}/challenge`, {
              method: "POST",
              body: JSON.stringify({
                challenge_type: "RESOLUTION",
                reason,
                attachment_ids: [],
              }),
            });
          }
          break;
        }
        case "propose-resolution": {
          const resolution = (changes as any)?.resolution;
          const summary = resolution?.notes || "Physical remediation completed and verified";
          let attachmentIds: string[] = [];
          if (resolution?.evidence?.length) {
            try {
              attachmentIds = await Promise.all(
                resolution.evidence
                  .filter((e: string) => e.startsWith("data:"))
                  .map((e: string, idx: number) => uploadDataUrl(e, idx))
              );
            } catch {
              // fallback
            }
          }
          await request(`/cases/${caseId}/resolve`, {
            method: "POST",
            body: JSON.stringify({
              remediation_summary: summary,
              attachment_ids: attachmentIds.length > 0 ? attachmentIds : ((row as any).attachments?.map((a: any) => a.id).filter(Boolean) || []),
              review_window_days: 7,
            }),
          });
          break;
        }
        case "note": {
          const noteText = changes.activity?.[0]?.note || "Staff note";
          const isVisible = changes.activity?.[0]?.public ?? false;
          await request(`/cases/${caseId}/activity`, {
            method: "POST",
            body: JSON.stringify({
              note: noteText,
              is_citizen_visible: isVisible,
            }),
          });
          break;
        }
        case "assign":
          await request(`/cases/${caseId}/assign`, { method: "POST", body: JSON.stringify(changes) });
          break;
        case "reassign":
          await request(`/cases/${caseId}/reassign`, {
            method: "POST",
            body: JSON.stringify({
              reason: changes.activity?.[0]?.note || "Reassignment requested",
            }),
          });
          break;
        default:
          break;
      }
      return row;
    }
    await delay();
    const row = demoRows.find((item) => item.id === id);
    if (!row) throw new ApiError("Complaint not found.", 404);
    const finalChanges: any = { ...changes };
    if (action === "confirm") {
      finalChanges.status = "resolved";
      finalChanges.evidenceVerified = true;
      const confirmAct = {
        title: "Citizen Satisfaction Verified",
        note: (changes as any)?.note || "Citizen verified satisfaction with resolution works. Case officially closed.",
        department: row.department,
        date: new Date().toISOString().slice(0, 10),
        public: true,
      };
      finalChanges.activity = [confirmAct, ...(row.activity || [])];
    } else if (action === "challenge") {
      finalChanges.status = "challenged";
      const challengeReason = (changes as any)?.challenge?.reason || "Citizen reopened case";
      finalChanges.challenge = { reason: challengeReason, evidence: [] };
      const reopenAct = {
        title: "Case Reopened by Citizen Objection",
        note: `Citizen contested resolution: ${challengeReason}. Escalated to municipal supervisor.`,
        department: row.department,
        date: new Date().toISOString().slice(0, 10),
        public: true,
      };
      finalChanges.activity = [reopenAct, ...(row.activity || [])];
    }
    const next = { ...row, ...finalChanges };
    demoRows = demoRows.map((item) => (item.id === id ? next : item));
    return next;
  },
  async trending(latitude: number, longitude: number): Promise<TrendingIssue[]> {
    if (isDemo) {
      await delay();
      return demoRows
        .filter((row) => row.status !== "resolved")
        .sort((a, b) => (b.upvoteCount ?? 0) - (a.upvoteCount ?? 0))
        .slice(0, 4)
        .map((row) => ({
          id: row.id,
          backendId: row.backendId ?? row.id,
          title: row.title,
          ward: row.ward,
          ...(row.wardNumber !== undefined ? { wardNumber: row.wardNumber } : {}),
          lat: row.lat,
          lng: row.lng,
          status: row.status,
          distanceMeters: 0,
          upvoteCount: row.upvoteCount ?? 0,
          priorityBand:
            row.priorityBand ??
            (row.priority === "Critical"
              ? "CRITICAL"
              : row.priority === "High"
                ? "HIGH"
                : "MEDIUM"),
          compositeScore: row.compositeScore ?? 0,
          upvoted: false,
        }));
    }
    if (!tokens) return [];
    const rows = await request<BackendTrendingIssue[]>(
      `/complaints/trending-nearby?lat=${encodeURIComponent(latitude)}&lng=${encodeURIComponent(longitude)}&radius_meters=2000`,
    );
    return rows.map((row) => ({
      id: row.tracking_number,
      backendId: row.id,
      title: row.title,
      ward: row.ward_name ?? "Ward assignment pending",
      ...(row.ward_number !== null ? { wardNumber: row.ward_number } : {}),
      lat: row.latitude,
      lng: row.longitude,
      status: row.status,
      distanceMeters: row.distance_meters,
      upvoteCount: row.upvote_count,
      priorityBand: row.priority_band as TrendingIssue["priorityBand"],
      compositeScore: row.composite_score,
      upvoted: row.upvoted_by_current_user,
    }));
  },
  async toggleUpvote(
    issue: TrendingIssue,
    latitude: number,
    longitude: number,
  ): Promise<BackendUpvoteResult> {
    if (isDemo) {
      await delay();
      const upvoted = !issue.upvoted;
      return {
        complaint_id: issue.backendId,
        upvote_count: Math.max(0, issue.upvoteCount + (upvoted ? 1 : -1)),
        upvoted,
        message: upvoted
          ? "You endorsed this issue and will receive resolution updates."
          : "Your endorsement was removed.",
      };
    }
    return request<BackendUpvoteResult>(`/complaints/${issue.backendId}/upvote`, {
      method: "POST",
      body: JSON.stringify({ latitude, longitude }),
    });
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
