import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import { Fragment, useMemo, useState } from "react";
import { isMobile } from "react-device-detect";
import { useTranslation } from "react-i18next";
import { LuArrowLeft, LuExternalLink, LuMessageCircle } from "react-icons/lu";
import { useNavigate } from "react-router-dom";
import { FAQ, FAQ_CATEGORIES, FaqEntry, searchFaq } from "./faq";

// **negrita** and `codigo` inside an answer paragraph
function Paragraph({ text }: { text: string }) {
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean);
  return (
    <p className="text-sm leading-relaxed">
      {parts.map((part, i) => (
        <Fragment key={i}>
          {part.startsWith("**") ? (
            <strong>{part.slice(2, -2)}</strong>
          ) : part.startsWith("`") ? (
            <code className="rounded bg-secondary px-1 text-xs">
              {part.slice(1, -1)}
            </code>
          ) : (
            part
          )}
        </Fragment>
      ))}
    </p>
  );
}

export default function Assistant() {
  const { t } = useTranslation("components/assistant");
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState<string>();
  const [selected, setSelected] = useState<FaqEntry>();

  const results = useMemo(() => {
    const found = query.trim() ? searchFaq(query) : FAQ;
    return category && !query.trim()
      ? found.filter((e) => e.category === category)
      : found;
  }, [query, category]);

  const goTo = (to: string) => {
    setOpen(false);
    navigate(to);
  };

  return (
    <>
      <button
        type="button"
        aria-label={t("open")}
        onClick={() => setOpen(true)}
        className={cn(
          "fixed z-40 flex items-center justify-center gap-2 rounded-full bg-gradient-to-br from-sky-500 to-violet-600 font-semibold text-white shadow-lg transition hover:brightness-110",
          // on phones, above the settings save bar and the bottom navigation
          isMobile
            ? "bottom-28 right-3 size-12"
            : "bottom-12 right-4 h-11 px-4 text-sm",
        )}
      >
        <LuMessageCircle className="size-5" />
        {!isMobile && t("button")}
      </button>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent
          side={isMobile ? "bottom" : "right"}
          className={cn(
            "flex flex-col gap-3",
            isMobile ? "h-[85dvh] rounded-t-2xl" : "w-full sm:max-w-md",
          )}
        >
          <SheetHeader>
            <SheetTitle>{t("title")}</SheetTitle>
            <SheetDescription>{t("desc")}</SheetDescription>
          </SheetHeader>

          {selected ? (
            <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
              <Button
                size="sm"
                className="self-start"
                onClick={() => setSelected(undefined)}
              >
                <LuArrowLeft className="mr-2 size-4" />
                {t("back")}
              </Button>
              <h3 className="text-base font-semibold">{selected.question}</h3>
              {selected.answer.map((text, i) => (
                <Paragraph key={i} text={text} />
              ))}
              {selected.link && (
                <Button
                  variant="select"
                  className="self-start"
                  onClick={() => goTo(selected.link!.to)}
                >
                  <LuExternalLink className="mr-2 size-4" />
                  {selected.link.label}
                </Button>
              )}
            </div>
          ) : (
            <>
              <Input
                autoFocus={!isMobile}
                value={query}
                placeholder={t("search")}
                onChange={(e) => setQuery(e.target.value)}
              />
              {!query.trim() && (
                <div className="flex flex-wrap gap-1.5">
                  {FAQ_CATEGORIES.map((c) => (
                    <button
                      key={c}
                      type="button"
                      onClick={() =>
                        setCategory(category === c ? undefined : c)
                      }
                      className={cn(
                        "rounded-full border px-2.5 py-1 text-xs",
                        category === c
                          ? "border-selected bg-selected text-white"
                          : "border-secondary-highlight text-muted-foreground",
                      )}
                    >
                      {c}
                    </button>
                  ))}
                </div>
              )}
              <ul className="min-h-0 flex-1 space-y-1 overflow-y-auto">
                {results.map((entry) => (
                  <li key={entry.id}>
                    <button
                      type="button"
                      onClick={() => setSelected(entry)}
                      className="w-full rounded-md p-2 text-left text-sm hover:bg-secondary"
                    >
                      {entry.question}
                      <span className="block text-xs text-muted-foreground">
                        {entry.category}
                      </span>
                    </button>
                  </li>
                ))}
                {results.length === 0 && (
                  <li className="p-2 text-sm text-muted-foreground">
                    {t("noResults")}
                  </li>
                )}
              </ul>
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
