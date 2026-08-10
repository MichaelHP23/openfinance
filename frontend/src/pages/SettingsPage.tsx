import { useState } from "react";
import { useForm } from "react-hook-form";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { PageHead, Card, Empty } from "../ui/Shell";
import {
  useSessions,
  useRevokeSession,
  useRevokeOtherSessions,
  useChangePassword,
  useEnroll2FA,
  useVerify2FA,
  useInvites,
  useCreateInvite,
  useRevokeInvite,
  useAuditLog,
} from "../auth/settings";

type Me = { role: string };
type PasswordForm = { current_password: string; new_password: string };
type CodeForm = { code: string };

function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: () => apiFetch<Me>("/auth/me") });
}

function SessionsCard() {
  const { data: sessions } = useSessions();
  const revoke = useRevokeSession();
  const revokeOthers = useRevokeOtherSessions();

  return (
    <Card>
      <h2 className="mb-3 font-display text-xl">Sessions</h2>
      {!sessions?.length ? (
        <Empty>No active sessions.</Empty>
      ) : (
        <ul className="flex flex-col gap-2">
          {sessions.map((s) => (
            <li key={s.id} className="flex items-center justify-between text-sm">
              <span>
                {s.is_current ? "This device" : "Other device"} · signed in{" "}
                {new Date(s.created_at).toLocaleDateString()}
              </span>
              {!s.is_current && (
                <button className="btn-ghost text-clay" onClick={() => revoke.mutate(s.id)}>
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
      <button className="btn-ghost mt-3 text-sm" onClick={() => revokeOthers.mutate()}>
        Log out other devices
      </button>
    </Card>
  );
}

function PasswordCard() {
  const change = useChangePassword();
  const { register, handleSubmit, reset, setError, formState: { errors, isSubmitting } } =
    useForm<PasswordForm>();

  const onSubmit = async (data: PasswordForm) => {
    try {
      await change.mutateAsync(data);
      reset();
    } catch (e) {
      setError("root", { message: (e as Error).message });
    }
  };

  return (
    <Card>
      <h2 className="mb-3 font-display text-xl">Password</h2>
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-3">
        <input
          type="password"
          placeholder="Current password"
          {...register("current_password", { required: true })}
        />
        <input
          type="password"
          placeholder="New password"
          {...register("new_password", { required: true, minLength: 6 })}
        />
        {errors.root && <span className="text-sm text-clay">{errors.root.message}</span>}
        <button disabled={isSubmitting} className="btn w-fit">
          {isSubmitting ? "…" : "Change password"}
        </button>
      </form>
    </Card>
  );
}

function TwoFACard() {
  const enroll = useEnroll2FA();
  const verify = useVerify2FA();
  const [enrolled, setEnrolled] = useState(false);
  const { register, handleSubmit, setError, formState: { errors, isSubmitting } } = useForm<CodeForm>();

  const onVerify = async (data: CodeForm) => {
    try {
      await verify.mutateAsync(data.code);
      setEnrolled(true);
    } catch (e) {
      setError("root", { message: (e as Error).message });
    }
  };

  return (
    <Card>
      <h2 className="mb-3 font-display text-xl">Two-factor authentication</h2>
      {enrolled ? (
        <p className="text-sm text-acid">2FA is enabled on your account.</p>
      ) : enroll.data ? (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-muted">
            Add this to your authenticator app, then enter a code to confirm:
          </p>
          <code className="break-all rounded-lg border border-line bg-[rgba(237,234,228,0.04)] p-2 text-xs">
            {enroll.data.provisioning_uri}
          </code>
          <form onSubmit={handleSubmit(onVerify)} className="flex gap-2">
            <input
              inputMode="numeric"
              placeholder="000000"
              className="flex-1"
              {...register("code", { required: true })}
            />
            <button disabled={isSubmitting} className="btn">
              {isSubmitting ? "…" : "Confirm"}
            </button>
          </form>
          {errors.root && <span className="text-sm text-clay">{errors.root.message}</span>}
        </div>
      ) : (
        <button className="btn w-fit" onClick={() => enroll.mutate()}>
          Enable 2FA
        </button>
      )}
    </Card>
  );
}

function InvitesCard() {
  const { data: invites } = useInvites();
  const create = useCreateInvite();
  const revoke = useRevokeInvite();
  const [link, setLink] = useState<string | null>(null);

  const onCreate = async () => {
    const invite = await create.mutateAsync();
    setLink(`${window.location.origin}/join/${invite.token}`);
  };

  return (
    <Card>
      <h2 className="mb-3 font-display text-xl">Household invites</h2>
      <p className="mb-3 text-sm text-muted">
        Share a link to add another member — no email is sent, you send it yourself.
      </p>
      {link && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-line p-2 text-xs">
          <code className="flex-1 break-all">{link}</code>
          <button className="btn-ghost" onClick={() => navigator.clipboard.writeText(link)}>
            Copy
          </button>
        </div>
      )}
      <button className="btn mb-4 w-fit" onClick={onCreate}>
        Generate invite link
      </button>
      {!invites?.length ? (
        <Empty>No pending invites.</Empty>
      ) : (
        <ul className="flex flex-col gap-2">
          {invites.map((i) => (
            <li key={i.id} className="flex items-center justify-between text-sm">
              <span>
                {i.used_at ? "Used" : `Expires ${new Date(i.expires_at).toLocaleDateString()}`}
              </span>
              {!i.used_at && (
                <button className="btn-ghost text-clay" onClick={() => revoke.mutate(i.id)}>
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function AuditLogCard() {
  const { data: events } = useAuditLog();
  return (
    <Card>
      <h2 className="mb-3 font-display text-xl">Audit log</h2>
      {!events?.length ? (
        <Empty>No events recorded yet.</Empty>
      ) : (
        <ul className="flex flex-col gap-2">
          {events.map((e) => (
            <li key={e.id} className="flex items-center justify-between text-sm">
              <span>{e.action}</span>
              <span className="text-muted">{new Date(e.created_at).toLocaleString()}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function SettingsPage() {
  const { data: me } = useMe();

  return (
    <>
      <PageHead title="Settings" sub="Your account, sessions, and security" />
      <div className="flex flex-col gap-5">
        <SessionsCard />
        <PasswordCard />
        <TwoFACard />
      </div>
      {me?.role === "owner" && (
        <div className="mt-5 flex flex-col gap-5">
          <InvitesCard />
          <AuditLogCard />
        </div>
      )}
    </>
  );
}
