import { useMemo } from "react";
import type { AuditFinding, AuditStatus, ToolExecution } from "../lib/schemas";
import { useAuditStore } from "../stores/audit-store";
import { useAuthStore } from "../stores/auth-store";

const severityRank: Record<AuditFinding["severity"], number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

const statusCopy: Record<AuditStatus, string> = {
  queued: "This audit is queued and waiting to start.",
  planning: "The agent is choosing the appropriate deterministic tools.",
  running_tools: "The scanner is collecting evidence from the submitted page.",
  generating_report: "The evidence is ready and the final report is being written.",
  completed: "The audit is complete.",
  failed: "The audit could not be completed.",
};

function titleCase(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function displayHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function fullDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function duration(value: number | null): string {
  if (value === null) return "Unknown";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} sec`;
}

function FindingCard({ finding }: { finding: AuditFinding }) {
  const severityTone = finding.severity === "critical" || finding.severity === "high"
    ? "bg-[#f4dfdc] text-[#873c35]"
    : finding.severity === "medium"
      ? "bg-[#f2ead1] text-[#755d18]"
      : "bg-[#e5eae5] text-[#526157]";

  return (
    <article className="border-b border-[var(--line)] py-5 last:border-b-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${severityTone}`}>
          {finding.severity}
        </span>
        <span className="text-xs font-medium text-[var(--muted)]">{finding.category}</span>
        {finding.is_release_blocker && <span className="text-xs font-semibold text-[#873c35]">Release blocker</span>}
      </div>
      <h3 className="mt-3 text-base font-semibold tracking-[-0.01em]">{finding.title}</h3>
      <p className="mt-2 text-sm leading-6 text-[var(--muted)]">{finding.description}</p>
      <div className="mt-4 border-l-2 border-[var(--accent)] pl-3">
        <p className="text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">Recommended fix</p>
        <p className="mt-1 text-sm leading-6">{finding.recommended_fix}</p>
      </div>
      <details className="mt-4 rounded-lg bg-[#f0f0eb] px-3.5 py-2.5 text-xs">
        <summary className="cursor-pointer font-semibold text-[var(--accent)]">
          Evidence from {titleCase(finding.source_tool)}
        </summary>
        <pre className="mt-3 overflow-x-auto whitespace-pre-wrap break-words font-mono leading-5 text-[#50524c]">
          {JSON.stringify(finding.evidence, null, 2)}
        </pre>
      </details>
    </article>
  );
}

function ToolRun({ tool }: { tool: ToolExecution }) {
  return (
    <details className="border-b border-[var(--line)] py-3 last:border-b-0">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 text-sm">
        <span className="font-medium">{titleCase(tool.tool_name)}</span>
        <span className={`text-xs font-semibold ${tool.success ? "text-[var(--accent)]" : "text-[#873c35]"}`}>
          {tool.success === null ? titleCase(tool.status) : tool.success ? "Passed" : "Needs review"}
        </span>
      </summary>
      <div className="mt-3 rounded-lg bg-[#f0f0eb] p-3 text-xs text-[var(--muted)]">
        <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1">
          <span>Duration: {duration(tool.duration_ms)}</span>
          <span>Sequence: {tool.sequence_number}</span>
        </div>
        {tool.errors.length > 0 && (
          <ul className="mb-3 space-y-1 text-[#873c35]">
            {tool.errors.map((error, index) => <li key={`${error.code}-${index}`}>{error.code}: {error.message}</li>)}
          </ul>
        )}
        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words font-mono leading-5 text-[#50524c]">
          {JSON.stringify(tool.data, null, 2)}
        </pre>
      </div>
    </details>
  );
}

export function AuditDetailPanel() {
  const token = useAuthStore((state) => state.token);
  const audit = useAuditStore((state) => state.selectedAudit);
  const selectAudit = useAuditStore((state) => state.selectAudit);
  const isLoading = useAuditStore((state) => state.isLoadingDetail);
  const findings = useMemo(
    () => [...(audit?.report?.findings ?? [])].sort((a, b) => severityRank[a.severity] - severityRank[b.severity]),
    [audit],
  );

  if (isLoading) {
    return (
      <section className="grid min-h-[560px] place-items-center rounded-2xl border border-[var(--line)] bg-[var(--surface)]" role="status">
        <div className="flex items-center gap-3 text-sm text-[var(--muted)]">
          <span className="h-2.5 w-2.5 animate-pulse rounded-full bg-[var(--accent)]" />
          Loading audit report
        </div>
      </section>
    );
  }

  if (!audit) {
    return (
      <section className="grid min-h-[560px] place-items-center rounded-2xl border border-dashed border-[#cfd0c8] bg-[var(--surface)] px-6 py-16 text-center">
        <div className="max-w-sm">
          <span className="mx-auto grid h-14 w-14 place-items-center rounded-2xl bg-[var(--accent-soft)] text-sm font-bold text-[var(--accent)]">01</span>
          <h2 className="mt-5 text-xl font-semibold tracking-[-0.02em]">Ready for a first scan</h2>
          <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
            Submit a URL to create a report, or choose a previous audit from the list to review its evidence.
          </p>
        </div>
      </section>
    );
  }

  const report = audit.report;
  const releaseTone = report?.release_status === "ready"
    ? "bg-[#dcebe1] text-[#285943]"
    : report?.release_status === "blocked"
      ? "bg-[#f4dfdc] text-[#873c35]"
      : "bg-[#eee9d9] text-[#735e26]";

  return (
    <section className="overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface)]">
      <header className="border-b border-[var(--line)] px-5 py-5 sm:px-7 sm:py-6">
        <div className="flex flex-col justify-between gap-5 sm:flex-row sm:items-start">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--accent)]">Audit #{audit.id}</p>
              <span className={`rounded-md px-2 py-1 text-[10px] font-bold uppercase tracking-wide ${releaseTone}`}>
                {report ? titleCase(report.release_status) : titleCase(audit.status)}
              </span>
            </div>
            <h2 className="mt-3 truncate text-2xl font-semibold tracking-[-0.03em] sm:text-3xl">{displayHost(audit.target_url)}</h2>
            <a
              href={audit.target_url}
              target="_blank"
              rel="noreferrer"
              className="mt-2 block truncate text-sm text-[var(--muted)] underline decoration-[#c7c8c0] underline-offset-4 hover:text-[var(--accent)]"
            >
              {audit.target_url}
            </a>
          </div>

          <div className="flex shrink-0 items-center gap-4">
            {audit.overall_score !== null && (
              <div className="text-right">
                <p className="text-4xl font-semibold tracking-[-0.05em]">{audit.overall_score}</p>
                <p className="text-[11px] font-medium uppercase tracking-wide text-[var(--muted)]">Score / 100</p>
              </div>
            )}
            <button
              type="button"
              onClick={() => token && void selectAudit(token, audit.id)}
              className="rounded-lg border border-[var(--line)] bg-white px-3 py-2 text-xs font-semibold transition hover:border-[#bcbdb5]"
            >
              Refresh
            </button>
          </div>
        </div>

        <dl className="mt-6 grid grid-cols-2 gap-x-5 gap-y-4 border-t border-[var(--line)] pt-5 text-xs sm:grid-cols-4">
          <div>
            <dt className="text-[var(--muted)]">Created</dt>
            <dd className="mt-1 font-medium">{fullDate(audit.created_at)}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Duration</dt>
            <dd className="mt-1 font-medium">{duration(audit.duration_ms)}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Tools run</dt>
            <dd className="mt-1 font-medium">{audit.tools_executed.length}</dd>
          </div>
          <div>
            <dt className="text-[var(--muted)]">Findings</dt>
            <dd className="mt-1 font-medium">{findings.length}</dd>
          </div>
        </dl>
      </header>

      {!report ? (
        <div className="px-5 py-14 text-center sm:px-7">
          <span className={`mx-auto block h-2.5 w-2.5 rounded-full ${audit.status === "failed" ? "bg-[#a24b43]" : "animate-pulse bg-[var(--accent)]"}`} />
          <h3 className="mt-4 text-lg font-semibold">{titleCase(audit.status)}</h3>
          <p className="mx-auto mt-2 max-w-md text-sm leading-6 text-[var(--muted)]">{audit.error_message || statusCopy[audit.status]}</p>
        </div>
      ) : (
        <div className="grid xl:grid-cols-[minmax(0,1fr)_300px]">
          <div className="px-5 py-6 sm:px-7">
            <section>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Executive summary</p>
              <p className="mt-3 text-[15px] leading-7">{report.executive_summary}</p>
              {report.is_mock && (
                <p className="mt-3 rounded-lg bg-[#eee9d9] px-3 py-2 text-xs text-[#735e26]">This report is marked as mock data.</p>
              )}
            </section>

            <section className="mt-8">
              <div className="flex items-end justify-between gap-4 border-b border-[var(--line)] pb-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Findings</p>
                  <h3 className="mt-1 text-lg font-semibold">Evidence-backed recommendations</h3>
                </div>
                <span className="text-sm font-semibold">{findings.length}</span>
              </div>
              {findings.length === 0 ? (
                <p className="py-8 text-sm leading-6 text-[var(--muted)]">No findings were produced from the available tool evidence.</p>
              ) : (
                findings.map((finding) => <FindingCard key={finding.id} finding={finding} />)
              )}
            </section>
          </div>

          <aside className="border-t border-[var(--line)] bg-[#f7f7f2] px-5 py-6 sm:px-7 xl:border-l xl:border-t-0 xl:px-5">
            <section>
              <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Audit request</p>
              <p className="mt-3 text-sm leading-6">{audit.instruction}</p>
            </section>

            <section className="mt-7 border-t border-[var(--line)] pt-6">
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Tool evidence</p>
                <span className="text-xs font-semibold">{audit.tool_executions.length}</span>
              </div>
              <div className="mt-2">
                {audit.tool_executions.length === 0 ? (
                  <p className="py-4 text-sm text-[var(--muted)]">No tool executions were saved.</p>
                ) : (
                  audit.tool_executions.map((tool) => <ToolRun key={tool.id} tool={tool} />)
                )}
              </div>
            </section>

            {report.screenshot_reference && (
              <section className="mt-7 border-t border-[var(--line)] pt-6">
                <p className="text-xs font-semibold uppercase tracking-[0.16em] text-[var(--muted)]">Screenshot reference</p>
                <p className="mt-2 break-all rounded-lg bg-white p-3 font-mono text-[11px] leading-5 text-[var(--muted)]">
                  {report.screenshot_reference}
                </p>
              </section>
            )}
          </aside>
        </div>
      )}
    </section>
  );
}
