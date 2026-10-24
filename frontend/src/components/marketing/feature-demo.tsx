import { AttendanceChatDemo } from "@/components/marketing/attendance-chat-demo";
import { CampusDemo } from "@/components/marketing/campus-demo";
import { ChallanDemo } from "@/components/marketing/challan-demo";
import type { MarketingCopy } from "@/components/marketing/copy";
import type { Locale } from "@/lib/i18n/config";
import { DiaryDemo } from "@/components/marketing/diary-demo";
import type { FeatureDemo as Demo } from "@/components/marketing/features";
import { PagesDemo } from "@/components/marketing/pages-demo";
import { RegisterDemo } from "@/components/marketing/register-demo";
import { RtlDemo } from "@/components/marketing/rtl-demo";

/** Demos narrow enough to sit beside the heading; the rest go full width below it. */
export const SIDE_DEMOS: ReadonlySet<Demo> = new Set(["diary", "attendance-chat", "register", "rtl"]);

export function FeatureDemo({ demo, copy, locale }: { demo: Demo; copy: MarketingCopy; locale: Locale }) {
  switch (demo) {
    case "diary":
      return (
        <DiaryDemo
          steps={copy.home.steps}
          pauseLabel={copy.home.pause}
          playLabel={copy.home.play}
          description={copy.home.demoDescription}
        />
      );
    case "attendance-chat":
      return <AttendanceChatDemo description={copy.demos.attendanceChat} />;
    case "challan":
      return <ChallanDemo description={copy.demos.challan} />;
    case "pages":
      return (
        <div className="rounded-3xl border border-mk-line bg-mk-card p-3 sm:p-6">
          <PagesDemo description={copy.demos.pages} />
        </div>
      );
    case "register":
      return <RegisterDemo description={copy.demos.register} />;
    case "campus":
      return <CampusDemo description={copy.demos.campus} />;
    case "rtl":
      return <RtlDemo locale={locale} />;
  }
}
