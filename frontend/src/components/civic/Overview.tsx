import { useSuspenseQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import {
  ArrowRight,
  ArrowUpRight,
  Plus,
  Files,
  LoaderCircle,
  ClipboardCheck,
  CheckCheck,
  MapPin,
  ShieldCheck,
  Clock3,
} from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { complaintsQuery, PageHeading, ComplaintTable, categories, StatusBadge } from "./shared";
import LocationMap from "./LocationMap";
import { toast } from "sonner";
import { PopularIssuesNearYou } from "./CitizenPages";
export default function Overview() {
  const { data: rows } = useSuspenseQuery(complaintsQuery);
  const { t } = useTranslation();
  const [tracking, setTracking] = useState("");
  const metrics = [
    {
      label: "total",
      count: rows.length,
      icon: Files,
      caption: "All your submitted reports",
      tone: "text-muted-foreground bg-muted",
    },
    {
      label: "active",
      count: rows.filter((row) => row.status === "in_progress").length,
      icon: LoaderCircle,
      caption: "Being addressed by departments",
      tone: "text-info bg-info-soft",
    },
    {
      label: "awaiting",
      count: rows.filter((row) => row.status === "review").length,
      icon: ClipboardCheck,
      caption: "Your confirmation is needed",
      tone: "text-warning bg-warning-soft",
    },
    {
      label: "resolved",
      count: rows.filter((row) => row.status === "resolved" && row.evidenceVerified).length,
      icon: CheckCheck,
      caption: "Evidence verified and closed",
      tone: "text-success bg-success-soft",
    },
  ];
  return (
    <div className="page-container fade-in">
      <PageHeading
        title={t("workspace")}
        subtitle={t("workspaceSubtitle")}
        action={
          <Button asChild className="h-11 px-5">
            <Link to="/report">
              <Plus className="size-4" />
              {t("newReport")}
            </Link>
          </Button>
        }
      />
      <div className="civic-banner mb-7">
        <div className="relative z-10">
          <span className="section-label text-primary">A BETTER CITY STARTS WITH YOU</span>
          <h2 className="mt-2 text-[24px] font-bold text-foreground">{t("reportTitle")}</h2>
          <p className="mt-2 text-xs text-muted-foreground">{t("reportSubtitle")}</p>
        </div>
        <Button
          asChild
          variant="outline"
          className="relative z-10 h-10 border-primary/25 bg-surface px-4 text-primary"
        >
          <Link to="/report">
            {t("submit")}
            <ArrowRight />
          </Link>
        </Button>
      </div>
      <PopularIssuesNearYou lat={rows[0]?.lat ?? 12.972} lng={rows[0]?.lng ?? 77.641} />
      <div className="mb-8 grid grid-cols-2 gap-4 xl:grid-cols-4">
        {metrics.map((metric) => (
          <div className="metric-card" key={metric.label}>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium text-muted-foreground">{t(metric.label)}</span>
              <div className={`grid size-8 shrink-0 place-items-center rounded-md ${metric.tone}`}>
                <metric.icon className="size-4" />
              </div>
            </div>
            <p className="mt-3 font-display text-[32px] font-bold leading-none">
              {String(metric.count).padStart(2, "0")}
            </p>
            <p className="mt-3 text-[10px] text-muted-foreground">{metric.caption}</p>
          </div>
        ))}
      </div>
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_310px]">
        <div className="min-w-0">
          <section className="panel">
            <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-5">
              <h2 className="text-sm font-bold">
                {t("recent")}
                <span className="ml-2 rounded bg-muted px-1.5 py-0.5 font-sans text-[10px] font-medium text-muted-foreground">
                  {rows.length}
                </span>
              </h2>
              <Link
                to="/complaints"
                className="flex items-center gap-1 text-[11px] font-medium text-primary"
              >
                {t("viewAll")}
                <ArrowRight className="size-3.5" />
              </Link>
            </div>
            <ComplaintTable rows={rows.slice(0, 4)} />
          </section>
          <section className="mt-7">
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-sm font-bold">{t("serviceCategories")}</h2>
              <span className="text-[10px] text-muted-foreground">5 service departments</span>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
              {categories.map((category) => (
                <Link
                  to="/report"
                  search={{ category: category.name }}
                  key={category.name}
                  className="group flex min-h-28 flex-col items-center justify-center gap-3 rounded-lg border border-border bg-surface px-2 py-4 text-center transition-colors hover:border-primary/40 hover:bg-secondary"
                >
                  <category.icon strokeWidth={1.5} className="size-6 text-primary" />
                  <span className="text-[10px] font-medium">{category.name}</span>
                </Link>
              ))}
            </div>
          </section>
          <div className="mt-6 flex items-start gap-3 border-t border-border py-5">
            <ShieldCheck className="mt-0.5 size-5 shrink-0 text-primary" />
            <div>
              <h3 className="text-xs font-bold">{t("accountability")}</h3>
              <p className="mt-1.5 max-w-xl text-[11px] leading-relaxed text-muted-foreground">
                {t("accountabilityText")}
              </p>
            </div>
          </div>
        </div>
        <div className="space-y-5">
          <section className="panel">
            <div className="flex items-center justify-between px-4 py-4">
              <h2 className="text-[13px] font-bold">{t("neighbourhood")}</h2>
              <MapPin className="size-4 text-primary" />
            </div>
            <LocationMap complaints={rows} />
            <div className="px-4 py-3">
              <div className="flex items-center justify-between text-[10px]">
                <span className="text-muted-foreground">Indiranagar & nearby wards</span>
                <span className="font-medium text-primary">{rows.length} reports</span>
              </div>
            </div>
            <div className="border-t border-border px-4 py-4">
              <Link
                to="/complaints/$id"
                params={{ id: rows[0]?.id ?? "BLR-2026-01482" }}
                className="flex items-start gap-2.5"
              >
                <span className="mt-1 size-1.5 shrink-0 rounded-full bg-info" />
                <div className="min-w-0">
                  <p className="truncate text-[11px] font-medium">
                    {rows[0]?.title ?? t("noComplaints")}
                  </p>
                  <p className="mt-1.5 flex items-center gap-1 text-[10px] text-muted-foreground">
                    <Clock3 className="size-3" />
                    {rows[0]?.address}
                  </p>
                </div>
                <ArrowUpRight className="ml-auto size-3.5 shrink-0 text-muted-foreground" />
              </Link>
            </div>
          </section>
          <section className="panel p-4">
            <div className="mb-3 flex items-center gap-2">
              <ClipboardCheck className="size-4 text-primary" />
              <h2 className="text-xs font-bold">{t("quickTrack")}</h2>
            </div>
            <form
              onSubmit={(event) => {
                event.preventDefault();
                if (!tracking.trim()) toast.error("Enter your tracking ID.");
              }}
            >
              <input
                aria-label="Tracking ID"
                className="form-field text-xs"
                value={tracking}
                onChange={(event) => setTracking(event.target.value.toUpperCase())}
                placeholder={t("trackingPlaceholder")}
              />
              <Button asChild variant="outline" className="mt-3 h-9 w-full text-xs">
                <Link to="/track" search={{ id: tracking }}>
                  {t("trackingButton")}
                  <ArrowRight className="size-3.5" />
                </Link>
              </Button>
            </form>
          </section>
          {rows.find((row) => row.status === "review") && (
            <section className="rounded-lg border border-warning/15 bg-warning-soft p-4">
              <span className="flex items-center gap-2 text-[11px] font-semibold text-warning">
                <ClipboardCheck className="size-4" />A resolution needs your review
              </span>
              <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                The street lighting team has proposed a fix for your report.
              </p>
              <Link
                to="/complaints/$id"
                params={{ id: rows.find((row) => row.status === "review")?.id ?? "" }}
                className="mt-3 flex items-center gap-1 text-[11px] font-semibold text-warning"
              >
                Review proposed resolution
                <ArrowRight className="size-3" />
              </Link>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
