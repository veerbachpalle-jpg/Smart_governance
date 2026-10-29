import { describe, expect, it } from "vitest";
import { filterAndRankRows, rankRows } from "@/components/civic/StaffPages";
import type { Complaint } from "@/lib/civic-types";

function complaint(overrides: Partial<Complaint>): Complaint {
  return {
    id: "GRV-TEST",
    title: "Test issue",
    description: "Detailed issue description",
    category: "Roads & footpaths",
    address: "Test address",
    ward: "Ward 104 - Indiranagar",
    lat: 12.972,
    lng: 77.641,
    status: "in_progress",
    date: "2026-10-29",
    department: "Roads & Infrastructure",
    priority: "Normal",
    evidenceVerified: false,
    attachments: [],
    activity: [],
    language: "en",
    ...overrides,
  };
}

describe("staff priority ordering", () => {
  it("keeps a critical issue with no upvotes above a medium issue with 500 upvotes", () => {
    const critical = complaint({
      id: "CRITICAL",
      priority: "Critical",
      priorityBand: "CRITICAL",
      upvoteCount: 0,
      compositeScore: 40_000,
    });
    const medium = complaint({
      id: "MEDIUM",
      priorityBand: "MEDIUM",
      upvoteCount: 500,
      compositeScore: 22_500,
    });
    expect(rankRows([medium, critical]).map((row) => row.id)).toEqual(["CRITICAL", "MEDIUM"]);
  });

  it("preserves composite priority order after department and ward filters", () => {
    const rows = [
      complaint({ id: "LOWER", compositeScore: 20_000 }),
      complaint({ id: "HIGHER", compositeScore: 40_000 }),
      complaint({ id: "OTHER", department: "Water & Drainage", compositeScore: 50_000 }),
    ];
    expect(
      filterAndRankRows(rows, "Roads & Infrastructure", "Ward 104 - Indiranagar").map(
        (row) => row.id,
      ),
    ).toEqual(["HIGHER", "LOWER"]);
  });
});
