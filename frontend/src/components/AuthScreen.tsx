import { useState, type FormEvent } from "react";
import { LoginInputSchema, RegisterInputSchema } from "../lib/schemas";
import { useAuthStore } from "../stores/auth-store";

type Mode = "login" | "register";
type FieldErrors = Partial<Record<"name" | "email" | "password" | "confirmPassword", string>>;

const inputClass =
  "mt-2 w-full rounded-xl border border-[var(--line)] bg-white px-3.5 py-3 text-[15px] text-[var(--ink)] outline-none transition placeholder:text-[#a1a29b] focus:border-[var(--accent)]";

function FieldError({ message }: { message?: string }) {
  return message ? <p className="mt-1.5 text-xs text-[#9b3d36]">{message}</p> : null;
}

export function AuthScreen() {
  const [mode, setMode] = useState<Mode>("login");
  const [values, setValues] = useState({
    name: "",
    email: "",
    password: "",
    confirmPassword: "",
  });
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const login = useAuthStore((state) => state.login);
  const register = useAuthStore((state) => state.register);
  const isSubmitting = useAuthStore((state) => state.isSubmitting);
  const serverError = useAuthStore((state) => state.error);
  const clearError = useAuthStore((state) => state.clearError);

  function switchMode(nextMode: Mode) {
    setMode(nextMode);
    setFieldErrors({});
    clearError();
  }

  function updateField(field: keyof typeof values, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    setFieldErrors((current) => ({ ...current, [field]: undefined }));
    clearError();
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const schema = mode === "login" ? LoginInputSchema : RegisterInputSchema;
    const candidate = mode === "login"
      ? { email: values.email, password: values.password }
      : values;
    const result = schema.safeParse(candidate);

    if (!result.success) {
      const errors: FieldErrors = {};
      for (const issue of result.error.issues) {
        const field = issue.path[0] as keyof FieldErrors;
        if (field && !errors[field]) errors[field] = issue.message;
      }
      setFieldErrors(errors);
      return;
    }

    try {
      if (mode === "login") {
        await login(LoginInputSchema.parse(candidate));
      } else {
        await register(RegisterInputSchema.parse(candidate));
      }
    } catch {
      // The store exposes the API error above the form.
    }
  }

  return (
    <main className="min-h-screen bg-[var(--canvas)] px-5 py-8 sm:px-8 lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(420px,560px)] lg:gap-8 lg:p-8">
      <section className="flex min-h-[300px] flex-col justify-between rounded-[28px] bg-[#22241f] p-7 text-[#f7f7f1] sm:p-10 lg:min-h-[calc(100vh-4rem)] lg:p-14">
        <a href="/" className="flex w-fit items-center gap-3 text-sm font-semibold tracking-tight">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-[#e7efe9] text-xs font-bold text-[var(--accent)]">SS</span>
          Site Scan AI
        </a>

        <div className="max-w-2xl py-14 lg:py-0">
          <p className="mb-5 text-xs font-semibold uppercase tracking-[0.2em] text-[#aeb9b0]">Evidence-first website audits</p>
          <h1 className="max-w-xl text-4xl font-semibold leading-[1.08] tracking-[-0.035em] sm:text-5xl">
            Find what your website is quietly getting wrong.
          </h1>
          <p className="mt-6 max-w-lg text-base leading-7 text-[#bfc2bb]">
            Run deterministic metadata, security, link, and browser checks—then turn the evidence into a focused audit report.
          </p>
        </div>

        <div className="grid max-w-xl grid-cols-2 gap-5 border-t border-white/10 pt-6 text-sm text-[#bfc2bb] sm:grid-cols-4">
          <span>Metadata</span>
          <span>Security</span>
          <span>Links</span>
          <span>Browser</span>
        </div>
      </section>

      <section className="flex items-center justify-center py-12 lg:min-h-[calc(100vh-4rem)] lg:py-0">
        <div className="w-full max-w-md">
          <div className="mb-8">
            <p className="text-sm font-medium text-[var(--accent)]">Your audit workspace</p>
            <h2 className="mt-2 text-3xl font-semibold tracking-[-0.03em] text-[var(--ink)]">
              {mode === "login" ? "Welcome back" : "Create your account"}
            </h2>
            <p className="mt-2 text-sm leading-6 text-[var(--muted)]">
              {mode === "login" ? "Sign in to continue to your saved website audits." : "Start scanning public websites in a few moments."}
            </p>
          </div>

          <div className="mb-7 grid grid-cols-2 rounded-xl border border-[var(--line)] bg-[#ecece6] p-1" aria-label="Authentication mode">
            {(["login", "register"] as const).map((item) => (
              <button
                key={item}
                type="button"
                onClick={() => switchMode(item)}
                className={`rounded-lg px-4 py-2.5 text-sm font-medium transition ${
                  mode === item ? "bg-white text-[var(--ink)] shadow-sm" : "text-[var(--muted)] hover:text-[var(--ink)]"
                }`}
                aria-pressed={mode === item}
              >
                {item === "login" ? "Log in" : "Register"}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} noValidate>
            <div className="space-y-4">
              {mode === "register" && (
                <label className="block text-sm font-medium text-[var(--ink)]">
                  Name
                  <input
                    className={inputClass}
                    value={values.name}
                    onChange={(event) => updateField("name", event.target.value)}
                    autoComplete="name"
                    placeholder="Your name"
                    aria-invalid={Boolean(fieldErrors.name)}
                  />
                  <FieldError message={fieldErrors.name} />
                </label>
              )}

              <label className="block text-sm font-medium text-[var(--ink)]">
                Email
                <input
                  className={inputClass}
                  type="email"
                  value={values.email}
                  onChange={(event) => updateField("email", event.target.value)}
                  autoComplete="email"
                  placeholder="you@example.com"
                  aria-invalid={Boolean(fieldErrors.email)}
                />
                <FieldError message={fieldErrors.email} />
              </label>

              <label className="block text-sm font-medium text-[var(--ink)]">
                Password
                <input
                  className={inputClass}
                  type="password"
                  value={values.password}
                  onChange={(event) => updateField("password", event.target.value)}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  placeholder="At least 8 characters"
                  aria-invalid={Boolean(fieldErrors.password)}
                />
                <FieldError message={fieldErrors.password} />
              </label>

              {mode === "register" && (
                <label className="block text-sm font-medium text-[var(--ink)]">
                  Confirm password
                  <input
                    className={inputClass}
                    type="password"
                    value={values.confirmPassword}
                    onChange={(event) => updateField("confirmPassword", event.target.value)}
                    autoComplete="new-password"
                    placeholder="Repeat your password"
                    aria-invalid={Boolean(fieldErrors.confirmPassword)}
                  />
                  <FieldError message={fieldErrors.confirmPassword} />
                </label>
              )}
            </div>

            {serverError && (
              <div className="mt-5 rounded-xl border border-[#e2c8c3] bg-[#f8ece9] px-4 py-3 text-sm text-[#7d342f]" role="alert">
                {serverError}
              </div>
            )}

            <button
              type="submit"
              disabled={isSubmitting}
              className="mt-6 w-full rounded-xl bg-[var(--accent)] px-4 py-3.5 text-sm font-semibold text-white transition hover:bg-[#1f4a36] disabled:cursor-wait disabled:opacity-60"
            >
              {isSubmitting ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
            </button>
          </form>

          <p className="mt-6 text-center text-sm text-[var(--muted)]">
            {mode === "login" ? "New here?" : "Already have an account?"}{" "}
            <button type="button" onClick={() => switchMode(mode === "login" ? "register" : "login")} className="font-semibold text-[var(--accent)] hover:underline">
              {mode === "login" ? "Create an account" : "Log in"}
            </button>
          </p>
        </div>
      </section>
    </main>
  );
}
