import { useEffect, useMemo, useState, type FormEvent } from "react";
import { AuditDetailPanel } from "./AuditDetailPanel";
import { AuditInputSchema, type AuditStatus } from "../lib/schemas";
import { useAuditStore } from "../stores/audit-store";
import { useAuthStore } from "../stores/auth-store";

const presets = [
  {
    label: "Full review",
    value: "Run a complete audit covering metadata, security headers, broken links, and browser runtime behavior.",
  },
  {
    label: "SEO basics",
    value: "Review metadata, headings, image alt text, canonical URL, language, and social sharing metadata.",
  },
  {
    label: "Security",
    value: "Inspect the response security headers and explain any missing protections with evidence.",
  },
  {
    label: "Runtime",
    value: "Load the page in a browser and inspect console errors, failed requests, page status, and load duration.",
  },
];

type AuditFieldErrors = Partial<Record<"target_url" | "instruction", string>>;

const statusLabels: Record<AuditStatus, string> = {
  queued: "Queued",
  planning: "Planning",
  running_tools: "Running tools",
  generating_report: "Writing report",
  completed: "Completed",
  failed: "Failed",
};

function displayHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function shortDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function StatusMark({ status }: { status: AuditStatus }) {
  const tone = status === "completed"
    ? "bg-[#dcebe1] text-[#285943]"
    : status === "failed"
      ? "bg-[#f4dfdc] text-[#873c35]"
      : "bg-[#eceae1] text-[#65645d]";
  return <span className={`rounded-md px-2 py-1 text-[11px] font-semibold ${tone}`}>{statusLabels[status]}</span>;
}

export function Dashboard() {
  const token = useAuthStore((state) => state.token);
  const user = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  const audits = useAuditStore((state) => state.audits);
  const selectedAudit = useAuditStore((state) => state.selectedAudit);
  const loadAudits = useAuditStore((state) => state.loadAudits);
  const selectAudit = useAuditStore((state) => state.selectAudit);
  const createAudit = useAuditStore((state) => state.createAudit);
  const clearAudits = useAuditStore((state) => state.clear);
  const clearAuditError = useAuditStore((state) => state.clearError);
  const isLoadingList = useAuditStore((state) => state.isLoadingList);
  const isCreating = useAuditStore((state) => state.isCreating);
  const auditError = useAuditStore((state) => state.error);
  const [targetUrl, setTargetUrl] = useState("");
  const [instruction, setInstruction] = useState(presets[0].value);
  const [fieldErrors, setFieldErrors] = useState<AuditFieldErrors>({});

  useEffect(() => {
    if (token) void loadAudits(token);
  }, [loadAudits, token]);

  const completedCount = useMemo(
    () => audits.filter((audit) => audit.status === "completed").length,
    [audits],
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = AuditInputSchema.safeParse({ target_url: targetUrl, instruction });
    if (!result.success) {
      const errors: AuditFieldErrors = {};
      for (const issue of result.error.issues) {
        const field = issue.path[0] as keyof AuditFieldErrors;
        if (field && !errors[field]) errors[field] = issue.message;
      }
      setFieldErrors(errors);
      return;
    }
    if (!token) return;

    try {
      await createAudit(token, result.data);
      setFieldErrors({});
    } catch {
      // The store displays the request error in context.
    }
  }

  function handleLogout() {
    clearAudits();
    logout();
  }

  function choosePreset(value: string) {
    setInstruction(value);
    setFieldErrors((current) => ({ ...current, instruction: undefined }));
    clearAuditError();
  }

  return (
    <div className="min-h-screen bg-[var(--canvas)] text-[var(--ink)]">
      <header className="border-b border-[var(--line)] bg-[var(--surface)]">
        <div className="mx-auto flex max-w-[1480px] items-center justify-between px-5 py-4 sm:px-8">
          <a href="/" className="flex items-center gap-3 text-sm font-semibold tracking-tight">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-[var(--accent)] text-xs font-bold text-white">SS</span>
            Site Scan AI
          </a>
          <div className="flex items-center gap-3 sm:gap-5">
            <div className="hidden text-right sm:block">
              <p className="text-sm font-medium">{user?.name}</p>
              <p className="text-xs text-[var(--muted)]">{user?.email}</p>
            </div>
            <button
              type="button"
              onClick={handleLogout}
              className="rounded-lg border border-[var(--line)] bg-white px-3.5 py-2 text-sm font-medium transition hover:border-[#bcbdb5] hover:bg-[#f7f7f3]"
            >
              Log out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1480px] px-5 py-7 sm:px-8 sm:py-10">
        <div className="mb-8 flex flex-col justify-between gap-5 sm:flex-row sm:items-end">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">Audit workspace</p>
            <h1 className="text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">What should we inspect?</h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-[var(--muted)]">
              Submit a public website and describe the checks you need. The report will only use evidence collected by the scanner.
            </p>
          </div>
          <div className="flex gap-6 text-sm">
            <div>
              <p className="text-2xl font-semibold tracking-tight">{audits.length}</p>
              <p className="text-xs text-[var(--muted)]">Total audits</p>
            </div>
            <div>
              <p className="text-2xl font-semibold tracking-tight">{completedCount}</p>
              <p className="text-xs text-[var(--muted)]">Completed</p>
            </div>
          </div>
        </div>

        <div className="grid gap-6 xl:grid-cols-[390px_minmax(0,1fr)]">
          <aside className="space-y-6">
            <section className="rounded-2xl border border-[var(--line)] bg-[var(--surface)] p-5 sm:p-6">
              <div className="mb-5">
                <p className="text-lg font-semibold tracking-[-0.02em]">New audit</p>
                <p className="mt-1 text-sm text-[var(--muted)]">Only public HTTP or HTTPS pages are accepted.</p>
              </div>

              <form onSubmit={handleSubmit} noValidate>
                <label className="block text-sm font-medium">
                  Website URL
                  <input
                    type="url"
                    value={targetUrl}
                    onChange={(event) => {
                      setTargetUrl(event.target.value);
                      setFieldErrors((current) => ({ ...current, target_url: undefined }));
                      clearAuditError();
                    }}
                    placeholder="https://example.com"
                    className="mt-2 w-full rounded-xl border border-[var(--line)] bg-white px-3.5 py-3 text-sm outline-none transition placeholder:text-[#a1a29b] focus:border-[var(--accent)]"
                    aria-invalid={Boolean(fieldErrors.target_url)}
                  />
                  {fieldErrors.target_url && <span className="mt-1.5 block text-xs text-[#9b3d36]">{fieldErrors.target_url}</span>}
                </label>

                <fieldset className="mt-5">
                  <legend className="text-sm font-medium">Audit focus</legend>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {presets.map((preset) => (
                      <button
                        key={preset.label}
                        type="button"
                        onClick={() => choosePreset(preset.value)}
                        className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium transition ${
                          instruction === preset.value
                            ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--accent)]"
                            : "border-[var(--line)] bg-white text-[var(--muted)] hover:text-[var(--ink)]"
                        }`}
                      >
                        {preset.label}
                      </button>
                    ))}
                  </div>
                </fieldset>

                <label className="mt-4 block text-sm font-medium">
                  Instructions
                  <textarea
                    value={instruction}
                    onChange={(event) => {
                      setInstruction(event.target.value);
                      setFieldErrors((current) => ({ ...current, instruction: undefined }));
                      clearAuditError();
                    }}
                    rows={5}
                    className="mt-2 w-full resize-y rounded-xl border border-[var(--line)] bg-white px-3.5 py-3 text-sm leading-6 outline-none transition placeholder:text-[#a1a29b] focus:border-[var(--accent)]"
                    aria-invalid={Boolean(fieldErrors.instruction)}
                  />
                  <span className="mt-1 flex justify-between gap-3 text-xs">
                    <span className="text-[#9b3d36]">{fieldErrors.instruction}</span>
                    <span className="ml-auto text-[var(--muted)]">{instruction.length}/2000</span>
                  </span>
                </label>

                {auditError && (
                  <div className="mt-4 rounded-xl border border-[#e2c8c3] bg-[#f8ece9] px-3.5 py-3 text-sm text-[#7d342f]" role="alert">
                    {auditError}
                  </div>
                )}

                <button
                  type="submit"
                  disabled={isCreating}
                  className="mt-5 w-full rounded-xl bg-[var(--accent)] px-4 py-3 text-sm font-semibold text-white transition hover:bg-[#1f4a36] disabled:cursor-wait disabled:opacity-60"
                >
                  {isCreating ? "Running audit…" : "Run audit"}
                </button>
                {isCreating && (
                  <p className="mt-3 text-center text-xs leading-5 text-[var(--muted)]" role="status">
                    The scanner is collecting evidence and preparing your report. This can take a moment.
                  </p>
                )}
              </form>
            </section>

            <section className="overflow-hidden rounded-2xl border border-[var(--line)] bg-[var(--surface)]">
              <div className="flex items-center justify-between border-b border-[var(--line)] px-5 py-4">
                <div>
                  <h2 className="text-sm font-semibold">Recent audits</h2>
                  <p className="mt-0.5 text-xs text-[var(--muted)]">Your latest 50 scans</p>
                </div>
                <button
                  type="button"
                  onClick={() => token && void loadAudits(token)}
                  disabled={isLoadingList}
                  className="text-xs font-semibold text-[var(--accent)] hover:underline disabled:opacity-50"
                >
                  {isLoadingList ? "Loading…" : "Refresh"}
                </button>
              </div>

              <div className="max-h-[520px] divide-y divide-[var(--line)] overflow-y-auto">
                {!isLoadingList && audits.length === 0 && (
                  <div className="px-5 py-8 text-center text-sm leading-6 text-[var(--muted)]">
                    No audits yet. Your first report will appear here.
                  </div>
                )}
                {audits.map((audit) => (
                  <button
                    type="button"
                    key={audit.id}
                    onClick={() => token && void selectAudit(token, audit.id)}
                    className={`w-full px-5 py-4 text-left transition hover:bg-[#f2f2ed] ${
                      selectedAudit?.id === audit.id ? "bg-[#eef2ed]" : ""
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold">{displayHost(audit.target_url)}</p>
                        <p className="mt-1 text-xs text-[var(--muted)]">{shortDate(audit.created_at)}</p>
                      </div>
                      {audit.overall_score !== null ? (
                        <span className="text-lg font-semibold tracking-tight">{audit.overall_score}</span>
                      ) : (
                        <StatusMark status={audit.status} />
                      )}
                    </div>
                    <p className="mt-2 line-clamp-2 text-xs leading-5 text-[var(--muted)]">{audit.instruction}</p>
                  </button>
                ))}
              </div>
            </section>
          </aside>

          <AuditDetailPanel />
        </div>
      </main>
    </div>
  );
}
