import type { ReactNode } from "react";
import { queryOptions, useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import {
  ArrowUpRight,
  CheckCheck,
  Clock3,
  CircleDot,
  ShieldCheck,
  RotateCcw,
  AlertCircle,
  Route,
  Droplets,
  Lightbulb,
  Trash2,
  Waves,
  Trees,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { civicApi } from "@/lib/civic-api";
import type { Complaint, Status, Category } from "@/lib/civic-types";
import { Button } from "@/components/ui/button";
export const complaintsQuery = queryOptions({
  queryKey: ["complaints"],
  queryFn: () => civicApi.list(),
  staleTime: 15000,
});
export const categories: { name: Category; icon: typeof Route; department: string }[] = [
  { name: "Roads & footpaths", icon: Route, department: "Roads & Bridges" },
  { name: "Water supply", icon: Droplets, department: "Water Supply" },
  { name: "Street lighting", icon: Lightbulb, department: "Electricity & Streetlights" },
  { name: "Waste management", icon: Trash2, department: "Sanitation & Solid Waste" },
  { name: "Stormwater & drainage", icon: Waves, department: "Stormwater & Drainage" },
  { name: "Parks & horticulture", icon: Trees, department: "Parks & Horticulture" },
];
export function CategoryIcon({
  category,
  className = "size-5",
}: {
  category: string;
  className?: string;
}) {
  const Icon = categories.find((item) => item.name === category)?.icon ?? Route;
  return <Icon className={className} />;
}
export function StatusBadge({ status, verified = false }: { status: Status; verified?: boolean }) {
  const { t } = useTranslation();
  const safe = status === "resolved" && !verified ? "review" : status;
  const Icon =
    safe === "resolved"
      ? CheckCheck
      : safe === "in_progress"
        ? CircleDot
        : safe === "reopened"
          ? RotateCcw
          : safe === "challenged"
            ? ShieldCheck
            : Clock3;
  return (
    <span
      className={`status-pill ${safe === "resolved" ? "status-done" : safe === "in_progress" ? "status-progress" : ["review", "challenged"].includes(safe) ? "status-pending" : "status-neutral"}`}
    >
      <Icon />
      {t(safe)}
    </span>
  );
}
export function PageHeading({
  title,
  subtitle,
  action,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-7 flex flex-wrap items-center justify-between gap-4">
      <div>
        <h1 className="text-[27px] font-bold leading-tight">{title}</h1>
        {subtitle && <p className="mt-2 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
export function ComplaintTable({ rows, staff = false }: { rows: Complaint[]; staff?: boolean }) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th>{t("complaint")}</th>
            <th className="hidden xl:table-cell">{t("department")}</th>
            <th>{t("status")}</th>
            <th className="hidden lg:table-cell">{t("reported")}</th>
            <th>
              <span className="sr-only">Open complaint</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>
                <div className="flex items-start gap-3">
                  <div className="mt-1 grid size-9 shrink-0 place-items-center rounded-md border border-border bg-background text-muted-foreground">
                    <CategoryIcon category={row.category} className="size-4" />
                  </div>
                  <div>
                    <Link
                      to={staff ? "/staff/case/$id" : "/complaints/$id"}
                      params={{ id: row.id }}
                      className="font-semibold hover:text-primary"
                    >
                      {row.title}
                    </Link>
                    <p className="mt-1.5 text-[11px] text-muted-foreground">
                      {row.id}
                      <span className="mx-2">·</span>
                      {row.category}
                    </p>
                    {staff && <div className="mt-2 flex flex-wrap gap-1.5"><span className={`status-pill ${row.priorityBand === "CRITICAL" ? "status-pending" : row.priorityBand === "HIGH" ? "status-progress" : "status-neutral"}`}>{row.priorityBand ?? "MEDIUM"}</span><span className="status-pill status-neutral">▲ {row.upvoteCount ?? 0} affected</span><span className="status-pill status-neutral"><Clock3 />{row.slaOverdue ? "SLA overdue" : row.slaSecondsRemaining !== undefined ? `${Math.max(0, Math.floor(row.slaSecondsRemaining / 3600))}h left` : "SLA pending"}</span></div>}
                  </div>
                </div>
              </td>
              <td className="hidden max-w-44 xl:table-cell">
                <span className="text-xs text-muted-foreground">{row.department}</span>
              </td>
              <td>
                <StatusBadge status={row.status} verified={row.evidenceVerified} />
              </td>
              <td className="hidden whitespace-nowrap text-xs text-muted-foreground lg:table-cell">
                {new Date(`${row.date}T12:00:00`).toLocaleDateString("en-GB", {
                  day: "2-digit",
                  month: "short",
                  year: "numeric",
                })}
              </td>
              <td>
                <Button variant="ghost" size="icon" asChild className="min-h-11 min-w-11">
                  <Link
                    to={staff ? "/staff/case/$id" : "/complaints/$id"}
                    params={{ id: row.id }}
                    aria-label={`Open ${row.id}`}
                  >
                    <ArrowUpRight className="size-4" />
                  </Link>
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && (
        <div className="py-16 text-center text-muted-foreground">{t("noComplaints")}</div>
      )}
    </div>
  );
}
export function ComplaintError() {
  const { refetch, error } = useSuspenseQuery(complaintsQuery);
  return error ? (
    <div className="p-6">
      <AlertCircle />
      <p>{error.message}</p>
      <Button onClick={() => refetch()}>Try again</Button>
    </div>
  ) : null;
}
