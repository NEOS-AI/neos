import Form from "next/form";

import { Input } from "./ui/input";
import { Label } from "./ui/label";

export function AuthForm({
  action,
  children,
  defaultEmail = "",
  oauthSection,
}: {
  action: NonNullable<
    string | ((formData: FormData) => void | Promise<void>) | undefined
  >;
  children: React.ReactNode;
  defaultEmail?: string;
  oauthSection?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 px-4 sm:px-16">
      {/* OAuth 로그인 섹션 */}
      {oauthSection && (
        <>
          {oauthSection}
          <div className="relative">
            <div className="absolute inset-0 flex items-center">
              <span className="w-full border-t" />
            </div>
            <div className="relative flex justify-center text-xs uppercase">
              <span className="bg-background px-2 text-muted-foreground">
                또는
              </span>
            </div>
          </div>
        </>
      )}

      {/* 이메일/비밀번호 로그인 폼 */}
      <Form action={action} className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label
            className="font-normal text-zinc-600 dark:text-zinc-400"
            htmlFor="email"
          >
            Email Address
          </Label>

          <Input
            autoComplete="email"
            autoFocus
            className="bg-muted text-md md:text-sm"
            defaultValue={defaultEmail}
            id="email"
            name="email"
            placeholder="user@acme.com"
            required
            type="email"
          />
        </div>

        <div className="flex flex-col gap-2">
          <Label
            className="font-normal text-zinc-600 dark:text-zinc-400"
            htmlFor="password"
          >
            Password
          </Label>

          <Input
            className="bg-muted text-md md:text-sm"
            id="password"
            name="password"
            required
            type="password"
          />
        </div>

        {children}
      </Form>
    </div>
  );
}
