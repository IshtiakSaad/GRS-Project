"use client";

// Where the SMS to a new officer, or to staff whose password an administrator reset, leads.

import { Suspense } from "react";
import { PasswordCode } from "@/components/password-code";
import { Loading } from "@/components/ui";

export default function Page() {
  return (
    <Suspense fallback={<Loading />}>
      <PasswordCode setup />
    </Suspense>
  );
}
