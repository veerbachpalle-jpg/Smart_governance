import { useState, useEffect, useMemo } from "react";
import { Link } from "@tanstack/react-router";
import { useQuery, useSuspenseQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useSimulation } from "@/lib/civic-sim";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCheck,
  Clock3,
  ClipboardList,
  FileCheck2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  X,
  Scale,
  Eye,
  Save,
  Upload,
  CheckCircle2,
  Wrench,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { toast } from "sonner";
import { complaintsQuery, PageHeading, ComplaintTable, StatusBadge, categories } from "./shared";
import { Timeline } from "./CitizenPages";
import { civicApi, isDemo, getSession } from "@/lib/civic-api";
import type { Complaint, Role, Status } from "@/lib/civic-types";
import LocationMap from "./LocationMap";
export function rankRows(rows: Complaint[]): Complaint[] {
  return [...rows].sort((a, b) => (b.compositeScore ?? 0) - (a.compositeScore ?? 0) || (b.upvoteCount ?? 0) - (a.upvoteCount ?? 0) || a.date.localeCompare(b.date));
}
export function filterAndRankRows(rows: Complaint[], department: string, ward: string): Complaint[] {
  return rankRows(rows).filter(row => (department === "all" || row.department === department) && (ward === "all" || row.ward === ward));
}
function SlaCountdown({ deadline, overdue = false }: { deadline: string | undefined; overdue: boolean | undefined }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 60_000); return () => window.clearInterval(timer); }, []);
  if (!deadline) return <span className="status-pill status-neutral"><Clock3 />SLA pending</span>;
  const remaining = new Date(deadline).getTime() - now; const absoluteMinutes = Math.max(0, Math.floor(Math.abs(remaining) / 60_000)); const hours = Math.floor(absoluteMinutes / 60); const minutes = absoluteMinutes % 60;
  return <span className={`status-pill ${overdue || remaining <= 0 ? 'status-pending' : 'status-neutral'}`}><Clock3 />{overdue || remaining <= 0 ? `SLA overdue ${hours}h ${minutes}m` : `SLA ${hours}h ${minutes}m left`}</span>;
}
function PrioritySignals({ row }: { row: Complaint }) {
  const band = row.priorityBand ?? (row.priority === 'Critical' ? 'CRITICAL' : row.priority === 'High' ? 'HIGH' : 'MEDIUM');
  return <div className="flex flex-wrap gap-2"><span className={`status-pill ${band === 'CRITICAL' ? 'status-pending' : band === 'HIGH' ? 'status-progress' : 'status-neutral'}`}>{band === 'CRITICAL' && <AlertTriangle />}{band}</span><span className="status-pill status-neutral">▲ {row.upvoteCount ?? 0} citizens affected</span><SlaCountdown deadline={row.slaDeadline} overdue={row.slaOverdue} /></div>;
}
function useRole() {
  const [role, setRole] = useState<Role | "citizen">("officer");
  useEffect(() => {
    const check = () => {
      const value = sessionStorage.getItem("civic-demo-role");
      setRole(
        isDemo && value && ["officer", "lead", "supervisor", "admin", "auditor"].includes(value)
          ? (value as Role)
          : (getSession()?.role ?? (isDemo ? "officer" : "citizen")),
      );
    };
    check();
    const timer = setInterval(check, 300);
    return () => clearInterval(timer);
  }, []);
  return role;
}
const access: Record<string, string[]> = {
  dashboard: ["officer", "lead", "supervisor", "admin", "auditor"],
  triage: ["officer", "lead", "supervisor", "admin"],
  cases: ["officer", "lead", "supervisor", "admin"],
  challenges: ["supervisor", "admin"],
  policies: ["admin"],
  audit: ["supervisor", "admin", "auditor"],
  quality: ["lead", "supervisor", "admin", "auditor"],
};
export function StaffPage({ view }: { view: string }) {
  const role = useRole();
  const { data: rows } = useSuspenseQuery(complaintsQuery);
  const { t } = useTranslation();

  // Read initial filter values from URL search params
  const [departmentFilter, setDepartmentFilterState] = useState(() => {
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      return sp.get("department") || "all";
    }
    return "all";
  });
  const [wardFilter, setWardFilterState] = useState(() => {
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      return sp.get("ward") || "all";
    }
    return "all";
  });
  const [statusFilter, setStatusFilterState] = useState(() => {
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      return sp.get("status") || "all";
    }
    return "all";
  });
  const [priorityFilter, setPriorityFilterState] = useState(() => {
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      return sp.get("priority") || "all";
    }
    return "all";
  });
  const [sortBy, setSortByState] = useState(() => {
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      return sp.get("sort") || "priority";
    }
    return "priority";
  });
  const [viewScope, setViewScope] = useState<"assigned" | "all">("all");

  const syncUrlParams = (updates: Record<string, string>) => {
    if (typeof window !== "undefined") {
      const sp = new URLSearchParams(window.location.search);
      for (const [k, v] of Object.entries(updates)) {
        if (v && v !== "all") sp.set(k, v);
        else sp.delete(k);
      }
      const newUrl = `${window.location.pathname}?${sp.toString()}`;
      window.history.replaceState(null, "", newUrl);
    }
  };

  const setDepartmentFilter = (val: string) => {
    setDepartmentFilterState(val);
    syncUrlParams({ department: val });
  };
  const setWardFilter = (val: string) => {
    setWardFilterState(val);
    syncUrlParams({ ward: val });
  };
  const setStatusFilter = (val: string) => {
    setStatusFilterState(val);
    syncUrlParams({ status: val });
  };
  const setPriorityFilter = (val: string) => {
    setPriorityFilterState(val);
    syncUrlParams({ priority: val });
  };
  const setSortBy = (val: string) => {
    setSortByState(val);
    syncUrlParams({ sort: val });
  };

  const departmentOptions = [...new Set([...categories.map(item => item.department), ...rows.map(row => row.department)])].filter(Boolean);
  const wardOptions = [...new Set(rows.map(row => row.ward))].filter(Boolean);

  // Filter rows
  const filteredRows = useMemo(() => {
    let result = [...rows];
    if (departmentFilter !== "all") {
      result = result.filter(r => r.department === departmentFilter);
    }
    if (wardFilter !== "all") {
      result = result.filter(r => r.ward === wardFilter);
    }
    if (statusFilter !== "all") {
      result = result.filter(r => r.status.toLowerCase() === statusFilter.toLowerCase());
    }
    if (priorityFilter !== "all") {
      result = result.filter(r => (r.priorityBand || r.priority || "").toUpperCase() === priorityFilter.toUpperCase());
    }
    if (sortBy === "upvotes") {
      result.sort((a, b) => (b.upvoteCount ?? 0) - (a.upvoteCount ?? 0));
    } else if (sortBy === "recent") {
      result.sort((a, b) => b.date.localeCompare(a.date));
    } else if (sortBy === "sla") {
      result.sort((a, b) => (a.slaDeadline || "").localeCompare(b.slaDeadline || ""));
    } else {
      result = rankRows(result);
    }
    return result;
  }, [rows, departmentFilter, wardFilter, statusFilter, priorityFilter, sortBy]);

  const rankedRows = rankRows(rows);
  if (!access[view])
    return (
      <div className="page-container">
        <PageHeading title="Page not found" />
        <Button asChild>
          <Link to="/staff/$view" params={{ view: "dashboard" }}>
            Staff overview
          </Link>
        </Button>
      </div>
    );
  if (!access[view]?.includes(role))
    return (
      <div className="page-container">
        <ShieldCheck className="mb-5 size-9 text-primary" />
        <PageHeading
          title="Restricted workspace"
          subtitle={
            role === "citizen"
              ? "Sign in with a staff account to continue."
              : `This page is not available to the ${role} role.`
          }
        />
        <p className="text-sm text-muted-foreground">
          Challenge reviews require a supervisor or administrator. Policies are administrator-only.
          Auditors have read-only access.
        </p>
        <Button asChild className="mt-6">
          <Link to="/signin">Sign in</Link>
        </Button>
      </div>
    );
  return (
    <div className="page-container fade-in">
      <PageHeading
        title={t(view === "policies" ? "policies" : view === "cases" ? "cases" : view)}
        subtitle={`${isDemo ? "Demonstration workspace" : "Municipal operations"} · ${role === "lead" ? "Department lead" : role.charAt(0).toUpperCase() + role.slice(1)}`}
        action={
          <span className="status-pill status-done">
            <ShieldCheck />
            Human oversight active
          </span>
        }
      />
      {["dashboard", "triage", "cases"].includes(view) && (
        <div className="mb-6 space-y-4">
          {/* Operational Map with clustering, colors, and legend */}
          <div className="panel overflow-hidden p-4">
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Operational Geographic Map ({filteredRows.length} Cases)
                </h3>
                <span className="rounded bg-primary/10 px-2 py-0.5 text-[10px] font-semibold text-primary">
                  Marker Clustering & Live Triage
                </span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                <span className="text-muted-foreground">Scope:</span>
                <button
                  type="button"
                  className={`rounded px-2.5 py-1 text-xs font-medium transition ${
                    departmentFilter !== "all"
                      ? "bg-primary text-primary-foreground"
                      : "bg-secondary text-secondary-foreground"
                  }`}
                  onClick={() => {
                    if (departmentFilter !== "all") setDepartmentFilter("all");
                    else setDepartmentFilter(departmentOptions[0] || "Roads & Infrastructure");
                  }}
                >
                  {departmentFilter !== "all" ? `Assigned (${departmentFilter})` : "All Departments"}
                </button>
              </div>
            </div>
            <div className="h-80 w-full overflow-hidden rounded-lg">
              <LocationMap complaints={filteredRows} large showLegend />
            </div>
          </div>

          {/* Unified URL-synced Filters Bar */}
          <div className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-surface p-4">
            <label className="text-xs font-semibold">
              Department
              <select
                className="form-field mt-1.5 min-w-44"
                value={departmentFilter}
                onChange={(e) => setDepartmentFilter(e.target.value)}
              >
                <option value="all">All Departments</option>
                {departmentOptions.map((dept) => (
                  <option key={dept} value={dept}>
                    {dept}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-xs font-semibold">
              Ward / Area
              <select
                className="form-field mt-1.5 min-w-40"
                value={wardFilter}
                onChange={(e) => setWardFilter(e.target.value)}
              >
                <option value="all">All Wards / Areas</option>
                {wardOptions.map((ward) => (
                  <option key={ward} value={ward}>
                    {ward}
                  </option>
                ))}
              </select>
            </label>

            <label className="text-xs font-semibold">
              Status
              <select
                className="form-field mt-1.5 min-w-36"
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
              >
                <option value="all">All Statuses</option>
                <option value="submitted">Submitted</option>
                <option value="in_progress">In Progress</option>
                <option value="review">Review Window</option>
                <option value="reopened">Reopened</option>
                <option value="challenged">Challenged</option>
                <option value="resolved">Resolved</option>
              </select>
            </label>

            <label className="text-xs font-semibold">
              Priority Band
              <select
                className="form-field mt-1.5 min-w-36"
                value={priorityFilter}
                onChange={(e) => setPriorityFilter(e.target.value)}
              >
                <option value="all">All Priorities</option>
                <option value="CRITICAL">Critical</option>
                <option value="HIGH">High</option>
                <option value="MEDIUM">Medium</option>
                <option value="LOW">Low</option>
              </select>
            </label>

            <label className="text-xs font-semibold">
              Sort By
              <select
                className="form-field mt-1.5 min-w-40"
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value)}
              >
                <option value="priority">Priority Score</option>
                <option value="upvotes">Citizen Upvotes</option>
                <option value="sla">SLA Urgency</option>
                <option value="recent">Most Recent</option>
              </select>
            </label>

            <div className="ml-auto self-end text-[11px] text-muted-foreground">
              {filteredRows.length} matching complaints · Query synced to URL
            </div>
          </div>
        </div>
      )}
      {view === "dashboard" && (
        <>
          <div className="mb-7 flex items-center gap-3 border-y border-border bg-secondary px-5 py-4">
            <Activity className="size-5 text-primary" />
            <div>
              <p className="text-xs font-semibold">
                {isDemo
                  ? "AI recommendations: demonstration mode"
                  : "AI service health: not yet connected"}
              </p>
              <p className="mt-1 text-[11px] text-muted-foreground">
                Manual triage remains available. Human approval is required for every
                recommendation.
              </p>
            </div>
          </div>
          <div className="mb-7 grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[
              {
                label: "Open cases",
                count: filteredRows.filter((r) => r.status !== "resolved").length,
                icon: ClipboardList,
              },
              {
                label: "Awaiting triage",
                count: filteredRows.filter((r) => r.status === "submitted").length,
                icon: SlidersHorizontal,
              },
              {
                label: "Safety-critical",
                count: filteredRows.filter((r) => r.priorityBand === "CRITICAL" || r.priority === "Critical").length,
                icon: AlertTriangle,
              },
              {
                label: "Challenge reviews",
                count: filteredRows.filter((r) => r.status === "challenged").length,
                icon: Scale,
              },
            ].map((item) => (
              <div className="metric-card" key={item.label}>
                <div className="flex items-center justify-between text-muted-foreground">
                  <span className="text-xs">{item.label}</span>
                  <item.icon className="size-5" />
                </div>
                <p className="mt-4 font-display text-3xl font-bold">
                  {String(item.count).padStart(2, "0")}
                </p>
              </div>
            ))}
          </div>
          <div className="mb-7 grid gap-5 lg:grid-cols-2">
            <section className="panel p-5">
              <h2 className="mb-4 text-sm font-bold">Safety-critical queue</h2>
              {filteredRows
                .filter((r) => r.priorityBand === "CRITICAL" || r.priority === "Critical")
                .map((row) => (
                  <Link
                    key={row.id}
                    to="/staff/case/$id"
                    params={{ id: row.id }}
                    className="flex items-center gap-3"
                  >
                    <AlertTriangle className="size-5 text-destructive" />
                    <div className="min-w-0 flex-1">
                      <p className="text-xs font-semibold">{row.title}</p>
                      <p className="mt-1 text-[11px] text-muted-foreground">{row.ward}</p>
                      <div className="mt-2"><PrioritySignals row={row} /></div>
                    </div>
                    <ArrowRight className="ml-auto size-4" />
                  </Link>
                ))}
            </section>
            <section className="panel p-5">
              <h2 className="text-sm font-bold">Service-level monitoring</h2>
              <p className="mt-3 text-xs leading-relaxed text-muted-foreground">Every queue item is re-ranked using severity, citizen endorsements, and bounded SLA urgency.</p>
              <div className="mt-3">{filteredRows[0] ? <SlaCountdown deadline={filteredRows[0].slaDeadline} overdue={filteredRows[0].slaOverdue} /> : <span className="status-pill status-neutral"><Clock3 />No active SLA</span>}</div>
            </section>
          </div>
          <section className="panel">
            <div className="flex justify-between p-5">
              <h2 className="text-sm font-bold">Active municipal cases</h2>
              <Link to="/staff/$view" params={{ view: "cases" }} className="text-xs text-primary">
                View all
                <ArrowRight className="ml-1 inline size-3" />
              </Link>
            </div>
            <ComplaintTable rows={filteredRows.slice(0, 5)} staff />
          </section>
        </>
      )}
      {(view === "triage" || view === "cases") && (
        <StaffQueue rows={filteredRows} triage={view === "triage"} />
      )}
      {view === "challenges" && <ChallengeQueue rows={rankedRows} />}
      {view === "policies" && <PolicyEditor />}
      {view === "audit" && <AuditView rows={rows} />}
      {view === "quality" && <QualityView />}
    </div>
  );
}
function StaffQueue({ rows, triage }: { rows: Complaint[]; triage: boolean }) {
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  return (
    <>
      <div className="mb-5 flex flex-wrap gap-3">
        <input
          className="form-field flex-1"
          placeholder="Search by ID, issue or ward"
          aria-label="Search staff queue"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select
          className="form-field w-auto"
          aria-label="Queue filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="all">All cases</option>
          <option value="Critical">Safety-critical</option>
          <option value="submitted">Manual triage</option>
          <option value="High">High priority</option>
        </select>
      </div>
      {triage && (
        <p className="mb-5 flex items-center gap-2 text-xs text-muted-foreground">
          <Eye className="size-4 text-primary" />
          AI outputs are suggestions, not findings. Review the original complaint before deciding.
        </p>
      )}
      <section className="panel">
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Case / original complaint</th>
                <th>Priority</th>
                <th className="hidden lg:table-cell">Ward</th>
                <th className="hidden lg:table-cell">Reported</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows
                .filter(
                  (r) =>
                    (filter === "all" || r.priority === filter || r.status === filter) &&
                    `${r.title} ${r.id} ${r.ward}`.toLowerCase().includes(search.toLowerCase()),
                )
                .map((row) => (
                  <tr key={row.id}>
                    <td>
                      <Link
                        to="/staff/case/$id"
                        params={{ id: row.id }}
                        className="text-xs font-semibold hover:text-primary"
                      >
                        {row.title}
                      </Link>
                      <p className="mt-1.5 text-[10px] text-muted-foreground">
                        {row.id} · {row.category}
                      </p>
                    </td>
                    <td>
                      <PrioritySignals row={row} />
                    </td>
                    <td className="hidden text-xs text-muted-foreground lg:table-cell">
                      {row.ward}
                    </td>
                    <td className="hidden text-xs text-muted-foreground lg:table-cell">
                      {row.date}
                    </td>
                    <td>
                      <StatusBadge status={row.status} verified={row.evidenceVerified} />
                    </td>
                    <td>
                      <Button asChild variant="ghost" size="icon">
                        <Link
                          to="/staff/case/$id"
                          params={{ id: row.id }}
                          aria-label={`Review ${row.id}`}
                        >
                          <ArrowRight />
                        </Link>
                      </Button>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
export function StaffCase({ id }: { id: string }) {
  const { data: rows } = useSuspenseQuery(complaintsQuery);
  const queryClient = useQueryClient();
  const role = useRole();
  const row = rows.find((r) => r.id === id);
  const [action, setAction] = useState("");
  const [reason, setReason] = useState("");
  const [recommendation, setRecommendation] = useState("");
  const [decision, setDecision] = useState("");
  const [note, setNote] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [evidence, setEvidence] = useState<string[]>([]);
  const [manual, setManual] = useState(false);
  const [department, setDepartment] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [priority, setPriority] = useState("Normal");
  const [overrideValue, setOverrideValue] = useState("");
  const { data: departments = [] } = useQuery({
    queryKey: ["municipal-departments"],
    queryFn: civicApi.departments,
    enabled: !isDemo,
  });
  if (!row)
    return (
      <div className="page-container">
        <PageHeading title="Case not found" />
      </div>
    );
  if (role === "citizen" || role === "auditor")
    return (
      <div className="page-container">
        <PageHeading
          title="Restricted case"
          subtitle="This case requires an operational staff role."
        />
      </div>
    );
  const critical = row.priority === "Critical";
  async function update(changes: Partial<Complaint>, type: string) {
    if (!row) return;
    setBusy(true);
    try {
      await civicApi.update(row.id, changes, type);
      await queryClient.invalidateQueries({ queryKey: ["complaints"] });
      toast.success(isDemo ? "Sample case updated." : "Case updated.");
      setAction("");
      setReason("");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Update failed.");
    } finally {
      setBusy(false);
    }
  }
  async function decide() {
    if (!row) return;
    if (decision !== "Accept" && reason.trim().length < 10) return;
    setBusy(true);
    try {
      await civicApi.decideTriage(
        row,
        recommendation as "Department routing" | "Priority",
        decision as "Accept" | "Override" | "Reject",
        reason,
        overrideValue,
      );
      await queryClient.invalidateQueries({ queryKey: ["complaints"] });
      toast.success(isDemo ? "Sample case updated." : "Triage decision recorded.");
      setRecommendation("");
      setReason("");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not record the decision.");
    } finally {
      setBusy(false);
    }
  }
  const choose = (rec: string, kind: string) => {
    setRecommendation(rec);
    setDecision(kind);
    setReason("");
    setOverrideValue(
      rec === "Department routing"
        ? row.departmentId ?? departments.find((item) => item.name === row.department)?.id ?? ""
        : row.priorityBand ?? (row.priority === "Critical" ? "CRITICAL" : row.priority === "High" ? "HIGH" : "MEDIUM"),
    );
  };
  return (
    <div className="page-container fade-in">
      <Link
        to="/staff/$view"
        params={{ view: "triage" }}
        className="mb-5 flex items-center gap-2 text-xs text-muted-foreground"
      >
        <ArrowRight className="size-3 rotate-180" />
        Triage queue
      </Link>
      <PageHeading
        title={row.title}
        subtitle={`${row.id} · ${row.ward}`}
        action={<StatusBadge status={row.status} verified={row.evidenceVerified} />}
      />
      <div className="mb-7 flex flex-wrap items-center gap-3 border-y border-border py-4">
        <ShieldCheck className="size-5 text-primary" />
        <span className="text-[10px] font-semibold uppercase tracking-[1px]">Accountable lead</span>
        <span className="text-xs font-semibold">{row.department}</span>
        <Button
          className="ml-auto"
          variant="outline"
          size="sm"
          onClick={() => {
            setAction("assign");
            setDepartment(row.department);
          }}
        >
          Assign / reassign
        </Button>
      </div>
      <div className="grid gap-7 xl:grid-cols-2">
        <div>
          <section>
            <h2 className="text-sm font-bold">Original complaint</h2>
            <OriginalReport text={row.description} language={row.language} />
            <div className="panel my-6">
              <LocationMap lat={row.lat} lng={row.lng} />
            </div>
            <p className="text-xs text-muted-foreground">{row.address}</p>
          </section>
          <section className="mt-8 border-t border-border pt-6">
            <h2 className="mb-4 text-sm font-bold">Case activity</h2>
            <Timeline row={row} internal />
          </section>
        </div>
        <div>
          <div className="mb-5 flex items-center justify-between">
            <h2 className="text-sm font-bold">Human triage workspace</h2>
            <label className="flex items-center gap-2 text-xs">
              <Switch checked={manual} onCheckedChange={setManual} />
              Manual form
            </label>
          </div>
          {manual ? (
            <section className="panel space-y-5 p-5">
              <h3 className="text-sm font-semibold">Manual assignment</h3>
              <label className="block text-xs">
                Department
                <select
                  className="form-field mt-2"
                  value={isDemo ? department : departmentId}
                  onChange={(e) => {
                    if (isDemo) setDepartment(e.target.value);
                    else {
                      setDepartmentId(e.target.value);
                      setDepartment(departments.find((item) => item.id === e.target.value)?.name ?? "");
                    }
                  }}
                >
                  <option value="">Select department</option>
                  {(isDemo ? categories.map((item) => ({ id: item.department, name: item.department })) : departments).map((item) => (
                    <option key={item.id} value={item.id}>{item.name}</option>
                  ))}
                </select>
              </label>
              <label className="block text-xs">
                Priority
                <select
                  className="form-field mt-2"
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                >
                  {["Normal", "High", "Critical"].map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
              </label>
              <label className="block text-xs">
                Written reasoning
                <textarea
                  className="form-field mt-2 min-h-24"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
              </label>
              <Button
                disabled={!(isDemo ? department : departmentId) || reason.trim().length < 10 || busy}
                onClick={async () => {
                  setBusy(true);
                  try {
                    if (isDemo) {
                      await update({ department, priority: priority as Complaint["priority"], status: "in_progress" }, "manual-triage");
                    } else {
                      await civicApi.submitManualTriage(row, {
                        departmentId,
                        priority: priority === "Critical" ? "CRITICAL" : priority === "High" ? "HIGH" : "MEDIUM",
                        notes: reason,
                      });
                      await queryClient.invalidateQueries({ queryKey: ["complaints"] });
                      toast.success("Manual triage recorded.");
                    }
                  } catch (error) {
                    toast.error(error instanceof Error ? error.message : "Could not save manual triage.");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Save human decision
                <Save />
              </Button>
            </section>
          ) : (
            <>
              <section className="panel mb-5 p-5">
                <span className="status-pill status-progress">
                  <Sparkles />
                  AI suggestion · Sample · 92% confidence
                </span>
                <h3 className="mt-4 text-sm font-bold">Interpretation report</h3>
                <div className="mt-4 grid gap-4 sm:grid-cols-2">
                  <div>
                    <h4 className="text-[10px] font-semibold uppercase text-muted-foreground">
                      Reported statements
                    </h4>
                    <p className="mt-2 text-xs leading-6">
                      The citizen reports a {row.category.toLowerCase()} issue at {row.address}.
                    </p>
                  </div>
                  <div>
                    <h4 className="text-[10px] font-semibold uppercase text-info">
                      Inferences · Not verified
                    </h4>
                    <p className="mt-2 text-xs leading-6 text-muted-foreground">
                      The report may require a site inspection. Physical conditions have not been
                      independently established.
                    </p>
                  </div>
                </div>
              </section>
              {[
                {
                  name: "Department routing",
                  value:
                    categories.find((c) => c.name === row.category)?.department ?? row.department,
                  reason:
                    "Category and reported location suggest this department. A human must verify jurisdiction.",
                },
                {
                  name: "Priority",
                  value: critical ? "Critical" : "High",
                  reason: critical
                    ? "Safety rule hit: uncovered utility opening near a school; possible fall hazard."
                    : "Potential disruption to public access. Severity has not been verified.",
                },
              ].map((rec) => {
                const isConfirmed =
                  rec.name === "Department routing"
                    ? Boolean(row.departmentConfirmed || ["in_progress", "review", "resolved", "challenged"].includes(row.status))
                    : Boolean(row.priorityConfirmed || ["in_progress", "review", "resolved", "challenged"].includes(row.status));

                return (
                  <section className="panel mb-5 p-5" key={rec.name}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className={`status-pill ${isConfirmed ? "status-resolved bg-success-soft text-success border border-success/30" : "status-progress"}`}>
                        {isConfirmed ? (
                          <>
                            <Check className="size-3.5" />
                            Confirmed · Official Finding
                          </>
                        ) : (
                          <>
                            <Sparkles className="size-3.5" />
                            AI suggestion · {rec.name === "Priority" ? "88" : "94"}% confidence
                          </>
                        )}
                      </span>
                      {isConfirmed && (
                        <span className="text-[11px] font-semibold text-success">
                          ✓ Saved to case
                        </span>
                      )}
                    </div>
                    <h3 className="mt-4 text-xs font-semibold text-muted-foreground">{rec.name}</h3>
                    <p className="mt-2 text-base font-bold text-foreground">{rec.value}</p>
                    <p
                      className={`mt-3 text-xs leading-6 ${critical && rec.name === "Priority" ? "text-warning" : "text-muted-foreground"}`}
                    >
                      {rec.reason}
                    </p>
                    <div className="mt-4 flex flex-wrap items-center gap-2">
                      {["Accept", "Override", "Reject"].map((kind) => (
                        <Button
                          key={kind}
                          size="sm"
                          variant={isConfirmed && kind === "Accept" ? "secondary" : kind === "Accept" ? "default" : "outline"}
                          className="h-8 text-xs"
                          onClick={() => choose(rec.name, kind)}
                        >
                          {kind === "Accept" ? (
                            <Check className="size-3.5 mr-1" />
                          ) : kind === "Reject" ? (
                            <X className="size-3.5 mr-1" />
                          ) : (
                            <SlidersHorizontal className="size-3.5 mr-1" />
                          )}
                          {kind}
                        </Button>
                      ))}
                    </div>
                  </section>
                );
              })}

              {/* NEXT OPERATIONAL ACTIONS WORKFLOW PANEL */}
              <section className="panel mb-5 p-5 border-2 border-primary/30 bg-primary-soft/10">
                <div className="flex items-center gap-2 text-primary font-bold text-sm">
                  <CheckCircle2 className="size-4.5" />
                  <span>Next Operational Actions</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground leading-relaxed">
                  Proceed with operational remediation. Assign department staff, initiate physical work, or propose a resolution to enter the 7-day citizen review window.
                </p>
                <div className="mt-4 flex flex-wrap items-center gap-2.5">
                  {["submitted", "routed"].includes(row.status) && (
                    <Button
                      size="sm"
                      disabled={busy}
                      className="bg-primary hover:bg-primary/90 text-primary-foreground font-semibold"
                      onClick={async () => {
                        setBusy(true);
                        try {
                          await civicApi.update(
                            row.id,
                            {
                              status: "in_progress",
                              department: row.department,
                              activity: [
                                {
                                  title: "Remediation Work Initiated",
                                  note: `Assigned to ${row.department} duty officer. Field work commenced.`,
                                  department: row.department,
                                  date: new Date().toISOString().slice(0, 10),
                                  public: true,
                                },
                                ...(row.activity || []),
                              ],
                            },
                            "assign",
                          );
                          await queryClient.invalidateQueries({ queryKey: ["complaints"] });
                          toast.success("Case assigned and moved to IN PROGRESS!");
                        } catch (e) {
                          toast.error(e instanceof Error ? e.message : "Failed to start work.");
                        } finally {
                          setBusy(false);
                        }
                      }}
                    >
                      <Wrench className="size-3.5 mr-1.5" />
                      Assign Duty Officer & Start Work
                    </Button>
                  )}

                  {["in_progress", "reopened"].includes(row.status) && (
                    <Button
                      size="sm"
                      className="bg-success hover:bg-success/90 text-success-foreground font-semibold"
                      onClick={() => {
                        setAction("resolve");
                        setNote("");
                      }}
                    >
                      <FileCheck2 className="size-3.5 mr-1.5" />
                      Propose Resolution (Open 7-Day Review)
                    </Button>
                  )}

                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setAction("assign");
                      setReason("");
                    }}
                  >
                    <SlidersHorizontal className="size-3.5 mr-1.5" />
                    Reassign Lead Department
                  </Button>
                </div>
              </section>
              <section className="panel p-5">
                <h3 className="text-sm font-bold">Related reports</h3>
                <p className="mt-2 text-xs text-muted-foreground">
                  No confirmed duplicate. Similarity matching is awaiting the external API contract.
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-4"
                  onClick={() => {
                    setManual(true);
                    setDepartmentId(row.departmentId ?? departments.find((item) => item.name === row.department)?.id ?? "");
                    setDepartment(row.department);
                    toast.info("Manual triage selected.");
                  }}
                >
                  Send to manual triage
                </Button>
              </section>
            </>
          )}
          <section className="mt-7 border-t border-border pt-6">
            <h2 className="text-sm font-bold">Add an update</h2>
            <textarea
              className="form-field mt-4 min-h-24"
              aria-label="Case update"
              placeholder="Write an official update or internal note."
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <label className="mt-3 flex items-center gap-2 text-xs">
              <Switch checked={visible} onCheckedChange={setVisible} />
              {visible ? "Citizen-visible update" : "Internal note only"}
            </label>
            {visible && (
              <div className="mt-3 rounded-md bg-secondary p-3">
                <span className="text-[10px] font-semibold text-primary">CITIZEN PREVIEW</span>
                <p className="mt-2 whitespace-pre-wrap text-xs">
                  {note || "Your update will appear here."}
                </p>
              </div>
            )}
            <Button
              className="mt-4"
              disabled={note.trim().length < 5 || busy}
              onClick={async () => {
                await update(
                  {
                    activity: [
                      {
                        title: visible ? "Official department update" : "Internal staff note",
                        note,
                        department: row.department,
                        date: new Date().toISOString().slice(0, 10),
                        public: visible,
                      },
                      ...row.activity,
                    ],
                  },
                  "note",
                );
                setNote("");
              }}
            >
              <Save />
              Save update
            </Button>
          </section>
        </div>
      </div>
      <div className="mt-8 flex flex-wrap items-center justify-between gap-3 border-y border-border py-5">
        <span className="text-xs text-muted-foreground">
          Only permitted next actions are available.
        </span>
        <div className="flex flex-wrap gap-3">
          {row.status === "submitted" && (
            <Button
              disabled={busy}
              onClick={() => {
                setManual(true);
                window.scrollTo({ top: 0, behavior: "smooth" });
              }}
            >
              Assign & start work
              <ArrowRight />
            </Button>
          )}
          {["in_progress", "reopened", "submitted"].includes(row.status) && (
            <Button
              variant="outline"
              onClick={() => {
                setAction("assign");
                setReason("");
              }}
            >
              Request Reassignment
              <SlidersHorizontal />
            </Button>
          )}
          {["in_progress", "reopened"].includes(row.status) && (
            <Button
              onClick={() => {
                setAction("resolve");
                setNote("");
              }}
            >
              Propose resolution
              <FileCheck2 />
            </Button>
          )}
          {role === "supervisor" && (
            <Button
              variant="secondary"
              onClick={() => {
                setAction("override-priority");
                setReason("");
              }}
            >
              Override Priority
              <AlertTriangle />
            </Button>
          )}
          {["review", "challenged", "resolved"].includes(row.status) && (
            <span className="status-pill status-neutral">
              <ShieldCheck />
              {row.status === "challenged"
                ? "Independent review required"
                : row.status === "resolved"
                  ? "Verified case · No state transition"
                  : "Awaiting citizen review and evidence verification"}
            </span>
          )}
        </div>
      </div>
      <Dialog
        open={Boolean(recommendation)}
        onOpenChange={(open) => {
          if (!open) setRecommendation("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {decision} {recommendation.toLowerCase()} suggestion
            </DialogTitle>
          <DialogDescription>
            This records a human decision. AI output is not an official finding.
          </DialogDescription>
          {decision === "Override" && recommendation === "Department routing" && (
            <label className="text-xs font-semibold">
              Replacement department
              <select
                className="form-field mt-2"
                value={overrideValue}
                onChange={(event) => setOverrideValue(event.target.value)}
              >
                <option value="">Select department</option>
                {departments.map((item) => (
                  <option key={item.id} value={item.id}>{item.name}</option>
                ))}
              </select>
            </label>
          )}
          {decision === "Override" && recommendation === "Priority" && (
            <label className="text-xs font-semibold">
              Replacement priority
              <select
                className="form-field mt-2"
                value={overrideValue}
                onChange={(event) => setOverrideValue(event.target.value)}
              >
                {["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((item) => (
                  <option key={item} value={item}>{item}</option>
                ))}
              </select>
            </label>
          )}
          </DialogHeader>
          <label htmlFor="decision-reason" className="text-xs font-semibold">
            Written reasoning {decision === "Accept" ? "(optional)" : "(required)"}
          </label>
          <textarea
            id="decision-reason"
            className="form-field min-h-24"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <Button
            disabled={busy || (decision !== "Accept" && (reason.trim().length < 10 || (decision === "Override" && !overrideValue)))}
            onClick={decide}
          >
            Save decision
            <Save />
          </Button>
        </DialogContent>
      </Dialog>
      <Dialog
        open={Boolean(action)}
        onOpenChange={(open) => {
          if (!open) setAction("");
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {action === "assign"
                ? "Request Jurisdictional Reassignment"
                : action === "override-priority"
                  ? "Supervisor Priority Override"
                  : "Propose a resolution"}
            </DialogTitle>
            <DialogDescription>
              {action === "assign"
                ? "Request transfer of accountable lead department with mandatory audited reasoning."
                : action === "override-priority"
                  ? "Direct supervisor override of case priority with immediate composite score recalculation."
                  : "A human officer must inspect the physical fix. Evidence and notes are required; this does not mark the case resolved."}
            </DialogDescription>
          </DialogHeader>
          {action === "override-priority" ? (
            <>
              <label htmlFor="override-priority-select" className="text-xs font-semibold">
                Target Priority Level
              </label>
              <select
                id="override-priority-select"
                className="form-field"
                value={priority}
                onChange={(e) => setPriority(e.target.value)}
              >
                <option value="CRITICAL">Critical</option>
                <option value="HIGH">High</option>
                <option value="MEDIUM">Medium</option>
                <option value="LOW">Low</option>
              </select>
              <label htmlFor="override-prio-reason" className="text-xs font-semibold">
                Supervisory Justification Note (Required)
              </label>
              <textarea
                id="override-prio-reason"
                className="form-field min-h-24"
                placeholder="Explain the reason for this priority override..."
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
              <Button
                disabled={busy || reason.trim().length < 5}
                onClick={async () => {
                  setBusy(true);
                  try {
                    await update(
                      {
                        priority: priority as Complaint["priority"],
                        activity: [
                          {
                            title: `Priority overridden to ${priority}`,
                            note: reason,
                            department: row.department,
                            date: new Date().toISOString().slice(0, 10),
                            public: true,
                          },
                          ...row.activity,
                        ],
                      },
                      "override-priority",
                    );
                    setAction("");
                    toast.success("Case priority updated.");
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                Apply Priority Override
                <AlertTriangle />
              </Button>
            </>
          ) : action === "assign" ? (
            <>
              <label htmlFor="assign-dept" className="text-xs">
                New accountable department
              </label>
              <select
                id="assign-dept"
                className="form-field"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
              >
                {categories.map((c) => (
                  <option key={c.department}>{c.department}</option>
                ))}
              </select>
              <textarea
                className="form-field min-h-24"
                aria-label="Reassignment reason"
                placeholder="Explain the reassignment request."
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
              <Button
                disabled={busy || reason.trim().length < 10}
                onClick={() =>
                  update(
                    {
                      department,
                      activity: [
                        {
                          title: "Accountable department reassigned",
                          note: reason,
                          department,
                          date: new Date().toISOString().slice(0, 10),
                          public: true,
                        },
                        ...row.activity,
                      ],
                    },
                    "reassign",
                  )
                }
              >
                Request reassignment
              </Button>
            </>
          ) : (
            <>
              <label htmlFor="resolution-note" className="text-xs">
                Officer inspection notes
              </label>
              <textarea
                id="resolution-note"
                className="form-field min-h-24"
                value={note}
                onChange={(e) => setNote(e.target.value)}
              />
              <label htmlFor="resolution-evidence" className="text-xs">
                Evidence photos · Required
              </label>
              <input
                id="resolution-evidence"
                type="file"
                multiple
                accept="image/jpeg,image/png,image/webp"
                onChange={async (e) => {
                  const files = Array.from(e.target.files ?? []);
                  if (
                    !files.length ||
                    files.length > 5 ||
                    files.some(
                      (f) =>
                        f.size > 5 * 1024 * 1024 ||
                        !["image/jpeg", "image/png", "image/webp"].includes(f.type),
                    )
                  ) {
                    toast.error("Upload up to 5 JPG, PNG or WebP photos, smaller than 5 MB.");
                    return;
                  }
                  const photos = await Promise.all(
                    files.map(
                      (file) =>
                        new Promise<string>((resolve) => {
                          const reader = new FileReader();
                          reader.onload = () =>
                            resolve(typeof reader.result === "string" ? reader.result : "");
                          reader.readAsDataURL(file);
                        }),
                    ),
                  );
                  setEvidence(photos);
                }}
              />
              <p className="text-[10px] text-muted-foreground">
                {evidence.length} evidence photos selected
              </p>
              <Button
                disabled={busy || note.trim().length < 20 || evidence.length === 0}
                onClick={() =>
                  update(
                    {
                      status: "review",
                      evidenceVerified: false,
                      resolution: {
                        notes: note,
                        evidence,
                        officer: "Assigned municipal officer",
                        deadline: new Date(Date.now() + 7 * 86400000).toISOString(),
                      },
                      activity: [
                        {
                          title: "Resolution proposed, awaiting your review",
                          note,
                          department: row.department,
                          date: new Date().toISOString().slice(0, 10),
                          public: true,
                        },
                        ...row.activity,
                      ],
                    },
                    "propose-resolution",
                  )
                }
              >
                Submit proposal
                <FileCheck2 />
              </Button>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
function ChallengeQueue({ rows }: { rows: Complaint[] }) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<Complaint | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [own, setOwn] = useState(false);
  async function decide(overturn: boolean) {
    if (!selected || !selected.challenge) return;
    setBusy(true);
    try {
      await civicApi.update(
        selected.id,
        {
          status: overturn ? "reopened" : "review",
          challenge: {
            ...selected.challenge,
            outcome: `${overturn ? "Overturned — case reopened" : "Upheld — awaiting evidence verification"}. ${reason}`,
          },
          activity: [
            {
              title: overturn ? "Challenge upheld: case reopened" : "Independent review completed",
              note: reason,
              department: "Independent review team",
              date: new Date().toISOString().slice(0, 10),
              public: true,
            },
            ...selected.activity,
          ],
        },
        "review-challenge",
      );
      await queryClient.invalidateQueries({ queryKey: ["complaints"] });
      setSelected(null);
      toast.success("Independent review decision recorded.");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Decision failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <p className="mb-5 text-xs text-muted-foreground">
        Independent review only. The original actor cannot decide the outcome of their own action.
      </p>
      <section className="panel">
        <ComplaintTable rows={rows.filter((r) => r.status === "challenged")} staff />
      </section>
      {rows
        .filter((r) => r.status === "challenged")
        .map((row) => (
          <div className="mt-5 flex justify-end" key={row.id}>
            <Button
              onClick={() => {
                setSelected(row);
                setReason("");
              }}
            >
              Review {row.id}
              <Scale />
            </Button>
          </div>
        ))}
      <Dialog
        open={Boolean(selected)}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Independent challenge review</DialogTitle>
            <DialogDescription>{selected?.id}</DialogDescription>
          </DialogHeader>
          <p className="text-xs font-semibold">Citizen challenge</p>
          <p className="text-sm text-muted-foreground">{selected?.challenge?.reason}</p>
          <p className="text-xs font-semibold">Original officer action</p>
          <p className="text-sm text-muted-foreground">
            {selected?.resolution?.notes ??
              "A temporary barrier was proposed in this sample case. Evidence is unverified."}
          </p>
          <p className="text-xs text-warning">
            Both sides’ evidence photos: {selected?.challenge?.evidence.length ?? 0} citizen ·{" "}
            {selected?.resolution?.evidence.length ?? 0} officer
          </p>
          {isDemo && (
            <label className="flex items-center gap-2 text-xs">
              <Switch checked={own} onCheckedChange={setOwn} />
              Simulate original actor reviewing
            </label>
          )}
          {own && (
            <p className="text-xs text-destructive" role="alert">
              Review blocked: the original actor cannot review their own action.
            </p>
          )}
          <label htmlFor="review-reason" className="text-xs">
            Written reasoning · Required
          </label>
          <textarea
            id="review-reason"
            className="form-field min-h-24"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          <div className="flex gap-3">
            <Button
              variant="outline"
              disabled={own || busy || reason.trim().length < 15}
              onClick={() => decide(false)}
            >
              Uphold original action
            </Button>
            <Button
              disabled={own || busy || reason.trim().length < 15}
              onClick={() => decide(true)}
            >
              Overturn & reopen
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
function PolicyEditor() {
  const [simulation, setSimulationRaw] = useSimulation();
  const setSimulation = (fn: (old: string[]) => string[]) => setSimulationRaw(fn(simulation));
  const [date, setDate] = useState("2026-10-15");
  const [version, setVersion] = useState(1);
  const [routes, setRoutes] = useState(categories.map((c) => ({ ...c })));
  return (
    <>
      <section className="mb-7">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-bold">
            Department routing rules{" "}
            <span className="status-pill status-neutral ml-2">v{version} · Sample</span>
          </h2>
          <label className="flex items-center gap-3 text-xs">
            Effective date
            <input
              type="date"
              className="form-field w-auto"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </label>
        </div>
        <div className="panel">
          <table className="data-table">
            <thead>
              <tr>
                <th>Service category</th>
                <th>Accountable department</th>
              </tr>
            </thead>
            <tbody>
              {routes.map((row, index) => (
                <tr key={row.name}>
                  <td>{row.name}</td>
                  <td>
                    <select
                      className="form-field text-xs"
                      aria-label={`${row.name} routing`}
                      value={row.department}
                      onChange={(e) =>
                        setRoutes((old) =>
                          old.map((r, i) =>
                            i === index ? { ...r, department: e.target.value } : r,
                          ),
                        )
                      }
                    >
                      {categories.map((c) => (
                        <option key={c.department}>{c.department}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Button
          className="mt-4"
          onClick={() => {
            if (!isDemo) return void toast.error("Policy API is not connected.");
            setVersion((v) => v + 1);
            toast.success(`Sample policy version saved. Effective ${date}.`);
          }}
        >
          <Save />
          Save new version
        </Button>
      </section>
      <section className="mb-7 border-t border-border pt-6">
        <h2 className="text-base font-bold">Priority & safety policy</h2>
        <p className="mt-3 text-xs text-muted-foreground">
          Sample safety policy · Uncovered utilities, exposed electrical infrastructure, and danger
          near schools require immediate human review.
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <span className="status-pill status-pending">
            <AlertTriangle />
            Safety rules require explicit human approval
          </span>
          <span className="status-pill status-neutral">No automatic case closure</span>
        </div>
      </section>
      <section className="border-t border-border pt-6">
        <h2 className="text-base font-bold">Failure simulation</h2>
        <p className="mt-2 text-xs text-muted-foreground">
          Demonstration controls only. No external services are affected.
        </p>
        {simulation.length > 0 && (
          <div className="mt-5 flex items-center gap-3 rounded-md border border-warning/20 bg-warning-soft p-4 text-xs text-warning">
            <AlertTriangle className="size-4" />
            Simulation active: {simulation.join(", ")}. Use manual triage.
          </div>
        )}
        <div className="mt-5 grid gap-4 md:grid-cols-2">
          {["AI unavailable", "Invalid AI output", "Delayed worker", "Failed notifications"].map(
            (item) => (
              <label
                key={item}
                className="flex items-center justify-between rounded-md border border-border bg-surface p-4 text-xs"
              >
                {item}
                <Switch
                  checked={simulation.includes(item)}
                  onCheckedChange={(checked) =>
                    setSimulation((old) =>
                      checked ? [...old, item] : old.filter((v) => v !== item),
                    )
                  }
                />
              </label>
            ),
          )}
        </div>
      </section>
      <section className="mt-7 border-t border-border pt-6">
        <h2 className="text-base font-bold">Departments & users</h2>
        <p className="mt-3 text-xs text-muted-foreground">
          5 sample departments. User provisioning and official policy publication require the
          external administrative API.
        </p>
      </section>
    </>
  );
}
function AuditView({ rows }: { rows: Complaint[] }) {
  const [search, setSearch] = useState("");
  const [result, setResult] = useState(false);
  const events = rows.flatMap((row) => row.activity.map((event) => ({ ...event, id: row.id })));
  return (
    <>
      <div className="mb-5 flex flex-wrap gap-3">
        <input
          className="form-field flex-1"
          aria-label="Filter audit log"
          placeholder="Filter by case ID, department or action"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <Button variant="outline" onClick={() => setResult(true)}>
          <ShieldCheck />
          Verify audit chain integrity
        </Button>
      </div>
      {result && (
        <div className="mb-5 flex items-center gap-3 rounded-md border border-warning/20 bg-warning-soft p-4 text-xs text-warning">
          <AlertTriangle className="size-5" />
          Not verified. The sample data has no signed chain or hashes. Connect the audit
          verification endpoint for a pass/fail result.
        </div>
      )}
      <section className="panel">
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr>
                <th>Timestamp</th>
                <th>Case ID</th>
                <th>Action</th>
                <th>Actor / department</th>
                <th>Visibility</th>
              </tr>
            </thead>
            <tbody>
              {events
                .filter((e) =>
                  `${e.id} ${e.title} ${e.department}`.toLowerCase().includes(search.toLowerCase()),
                )
                .map((e, i) => (
                  <tr key={`${e.id}-${i}`}>
                    <td>{e.date}</td>
                    <td className="whitespace-nowrap text-primary">{e.id}</td>
                    <td>{e.title}</td>
                    <td>{e.department}</td>
                    <td>
                      <span className="status-pill status-neutral">
                        {e.public ? "Citizen visible" : "Internal"}
                      </span>
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}
function QualityView() {
  return (
    <>
      <div className="mb-7 flex items-center gap-3 border-y border-border bg-secondary p-5">
        <Activity className="size-5 text-primary" />
        <p className="text-xs">
          No official evaluation run is available. Accuracy and recall are not reported without
          verified evaluation data.
        </p>
      </div>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
        {[
          "Category accuracy",
          "Routing accuracy",
          "Safety-critical recall",
          "Duplicate precision / recall",
          "Abstention rate",
          "Latest evaluation run",
        ].map((label) => (
          <div className="metric-card" key={label}>
            <h2 className="text-xs text-muted-foreground">{label}</h2>
            <p className="my-4 text-2xl font-semibold">—</p>
            <p className="text-[10px] text-muted-foreground">Awaiting evaluation service</p>
          </div>
        ))}
      </div>
      <div className="mt-7 grid gap-5 lg:grid-cols-2">
        <section className="panel p-6">
          <h2 className="text-sm font-bold">Evaluation history</h2>
          <div className="flex h-44 items-center justify-center text-xs text-muted-foreground">
            No evaluation runs recorded
          </div>
        </section>
        <section className="panel p-6">
          <h2 className="text-sm font-bold">Confusion matrix</h2>
          <ConfusionMatrix />
        </section>
      </div>
      <section className="mt-7 border-t border-border pt-6">
        <h2 className="text-sm font-bold">Safety-critical false negatives</h2>
        <FalseNegatives />
      </section>
    </>
  );
}

const matrixLabels = ["Roads", "Water", "Lighting", "Waste", "Safety"];
const matrixSample = [
  [42, 3, 0, 1, 2],
  [2, 37, 0, 2, 1],
  [0, 1, 29, 0, 0],
  [1, 2, 0, 33, 0],
  [3, 1, 0, 0, 24],
];
function ConfusionMatrix() {
  const max = Math.max(...matrixSample.flat());
  return (
    <div className="mt-4 overflow-x-auto">
      <p className="mb-3 text-[10px] text-muted-foreground">
        Sample evaluation set · Rows: human-verified category · Columns: AI recommendation
      </p>
      <table className="text-[11px]">
        <thead>
          <tr>
            <th className="p-1" />
            {matrixLabels.map((l) => (
              <th key={l} className="p-1 font-medium text-muted-foreground">
                {l}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {matrixSample.map((r, i) => (
            <tr key={matrixLabels[i]}>
              <th className="p-1 text-left font-medium text-muted-foreground">{matrixLabels[i]}</th>
              {r.map((v, j) => (
                <td
                  key={j}
                  className="size-11 border border-border text-center font-semibold"
                  style={{
                    backgroundColor:
                      i === j
                        ? `color-mix(in oklab, var(--primary) ${15 + (45 * v) / max}%, transparent)`
                        : v > 0
                          ? `color-mix(in oklab, var(--destructive) ${10 + (40 * v) / max}%, transparent)`
                          : undefined,
                  }}
                >
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
const falseNegatives = [
  {
    id: "BLR-2026-01391",
    report: "Exposed wire near bus stop",
    ai: "Street lighting · Medium",
    verified: "Electricity & Streetlights · Critical",
    reviewer: "Supervisor",
  },
  {
    id: "BLR-2026-01377",
    report: "Manhole cover shifted on main road",
    ai: "Roads & footpaths · Medium",
    verified: "Roads & Bridges · High",
    reviewer: "Roads Officer",
  },
  {
    id: "BLR-2026-01352",
    report: "Tree branch hanging over school gate",
    ai: "Sanitation & Solid Waste · Low",
    verified: "Parks & Horticulture · High",
    reviewer: "Supervisor",
  },
];
function FalseNegatives() {
  return (
    <>
      <p className="mt-3 text-xs text-muted-foreground">
        Sample evaluation cases where the AI under-rated a safety issue. Each was corrected by a
        human reviewer.
      </p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-2 pr-4 font-medium">Case</th>
              <th className="py-2 pr-4 font-medium">Report</th>
              <th className="py-2 pr-4 font-medium">AI recommendation</th>
              <th className="py-2 pr-4 font-medium">Human-verified</th>
              <th className="py-2 font-medium">Corrected by</th>
            </tr>
          </thead>
          <tbody>
            {falseNegatives.map((f) => (
              <tr key={f.id} className="border-b border-border">
                <td className="py-3 pr-4 font-mono">{f.id}</td>
                <td className="py-3 pr-4">{f.report}</td>
                <td className="py-3 pr-4 text-muted-foreground">{f.ai}</td>
                <td className="py-3 pr-4 font-semibold text-destructive">{f.verified}</td>
                <td className="py-3">{f.reviewer}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
function OriginalReport({ text, language }: { text: string; language: string }) {
  const [translated, setTranslated] = useState(false);
  const isEnglish = language === "en";
  return (
    <>
      <p className="mt-4 text-sm leading-7 text-muted-foreground">
        {translated && !isEnglish ? `[English translation · Sample] ${text}` : text}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>Original language: {language.toUpperCase()}</span>
        {isEnglish ? (
          <span>· No translation needed</span>
        ) : (
          <Button
            size="sm"
            variant="outline"
            type="button"
            onClick={() => setTranslated((v) => !v)}
          >
            {translated ? "Show original" : "Show English translation"}
          </Button>
        )}
      </div>
      <p className="mt-2 text-[10px] text-muted-foreground">
        Machine translations are aids only. Decisions must reference the original text.
      </p>
    </>
  );
}
