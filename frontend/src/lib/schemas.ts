import { z } from "zod";

const isoDate = z.string().datetime({ offset: true });
const nullableDate = isoDate.nullable();
const dataRecord = z.record(z.string(), z.unknown());

export const LoginInputSchema = z.object({
  email: z.string().trim().min(1, "Email is required.").email("Enter a valid email address."),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters.")
    .max(128, "Password must be 128 characters or fewer."),
});

export const RegisterInputSchema = z
  .object({
    name: z
      .string()
      .trim()
      .min(3, "Name must be at least 3 characters.")
      .max(50, "Name must be 50 characters or fewer."),
    email: z.string().trim().min(1, "Email is required.").email("Enter a valid email address."),
    password: z
      .string()
      .min(8, "Password must be at least 8 characters.")
      .max(128, "Password must be 128 characters or fewer."),
    confirmPassword: z.string(),
  })
  .refine((value) => value.password === value.confirmPassword, {
    message: "Passwords do not match.",
    path: ["confirmPassword"],
  });

export const AuditInputSchema = z.object({
  target_url: z
    .string()
    .trim()
    .min(1, "Website URL is required.")
    .url("Enter a complete URL, including https://")
    .refine((value) => ["http:", "https:"].includes(new URL(value).protocol), {
      message: "Only public HTTP and HTTPS URLs can be scanned.",
    }),
  instruction: z
    .string()
    .trim()
    .min(3, "Add a short instruction for the audit.")
    .max(2000, "Instruction must be 2,000 characters or fewer."),
});

export const UserSchema = z
  .object({
    id: z.number().int().positive(),
    name: z.string(),
    email: z.string().email(),
    is_active: z.boolean(),
    created_at: isoDate,
    updated_at: isoDate,
  })
  .passthrough();

export const TokenSchema = z.object({
  access_token: z.string().min(1),
  token_type: z.literal("bearer"),
  expires_in: z.number().int().positive(),
});

export const AuditStatusSchema = z.enum([
  "queued",
  "planning",
  "running_tools",
  "generating_report",
  "completed",
  "failed",
]);

export const ReleaseStatusSchema = z.enum(["ready", "needs_attention", "blocked", "unknown"]);
export const FindingSeveritySchema = z.enum(["info", "low", "medium", "high", "critical"]);

export const AuditFindingSchema = z
  .object({
    id: z.string(),
    category: z.enum(["SEO", "Security", "Reliability", "Accessibility", "Browser"]),
    severity: FindingSeveritySchema,
    title: z.string(),
    description: z.string(),
    evidence: dataRecord,
    recommended_fix: z.string(),
    source_tool: z.enum([
      "inspect_metadata",
      "inspect_security_headers",
      "check_broken_links",
      "inspect_browser",
    ]),
    is_release_blocker: z.boolean(),
  })
  .passthrough();

export const AuditReportSchema = z
  .object({
    overall_score: z.number().int().min(0).max(100).nullable(),
    release_status: ReleaseStatusSchema,
    executive_summary: z.string(),
    findings: z.array(AuditFindingSchema),
    screenshot_reference: z.string().nullable(),
    generated_at: isoDate,
    schema_version: z.string(),
    is_mock: z.boolean(),
  })
  .passthrough();

export const ToolExecutionSchema = z
  .object({
    id: z.number().int().positive(),
    tool_name: z.string(),
    arguments: dataRecord,
    status: z.string(),
    success: z.boolean().nullable(),
    data: dataRecord,
    errors: z.array(z.object({ code: z.string(), message: z.string() })),
    started_at: nullableDate,
    completed_at: nullableDate,
    duration_ms: z.number().int().nonnegative().nullable(),
    sequence_number: z.number().int(),
    screenshot_reference: z.string().nullable(),
    created_at: isoDate,
  })
  .passthrough();

export const AuditSummarySchema = z
  .object({
    id: z.number().int().positive(),
    target_url: z.string().url(),
    instruction: z.string(),
    status: AuditStatusSchema,
    overall_score: z.number().int().min(0).max(100).nullable(),
    release_status: ReleaseStatusSchema.nullable(),
    error_message: z.string().nullable(),
    created_at: isoDate,
    started_at: nullableDate,
    completed_at: nullableDate,
    duration_ms: z.number().int().nonnegative().nullable(),
    updated_at: isoDate,
    tools_executed: z.array(z.string()),
  })
  .passthrough();

export const AuditDetailSchema = AuditSummarySchema.extend({
  report: AuditReportSchema.nullable(),
  tool_executions: z.array(ToolExecutionSchema),
});

export type LoginInput = z.infer<typeof LoginInputSchema>;
export type RegisterInput = z.infer<typeof RegisterInputSchema>;
export type AuditInput = z.infer<typeof AuditInputSchema>;
export type User = z.infer<typeof UserSchema>;
export type AuditStatus = z.infer<typeof AuditStatusSchema>;
export type AuditSummary = z.infer<typeof AuditSummarySchema>;
export type AuditDetail = z.infer<typeof AuditDetailSchema>;
export type AuditFinding = z.infer<typeof AuditFindingSchema>;
export type ToolExecution = z.infer<typeof ToolExecutionSchema>;
