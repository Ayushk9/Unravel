import { useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";
import { Send } from "lucide-react";
import type { Citation, Provenance } from "@/api/types";
import { questionAnswerResultSchema } from "@/api/schemas";
import { usePolicy, useAskQuestion } from "@/api/endpoints/policies";
import { useJobPolling } from "@/api/endpoints/jobs";
import { useDocumentFile } from "@/api/endpoints/documents";
import { VoiceInput } from "@/components/VoiceInput";
import { AbstentionCard, CitationList, CitedProse, DocumentViewer, ErrorState, Skeleton } from "@/components/primitives";
import { productLabel } from "@/lib/policyLabels";

const SUGGESTED_QUESTIONS = ["Is my knee surgery covered?", "What happens if I choose a ₹12,000/day room?"];

export function PolicyAsk() {
  const { id } = useParams<{ id: string }>();
  const policy = usePolicy(id ?? null);
  const [searchParams, setSearchParams] = useSearchParams();
  const jobId = searchParams.get("q");

  const [question, setQuestion] = useState("");
  const [activeProvenance, setActiveProvenance] = useState<Provenance | null>(null);
  const askMutation = useAskQuestion(id ?? "");
  const jobQuery = useJobPolling(jobId, questionAnswerResultSchema);
  // The document a citation points at (D-26), so its highlight lands on the real page.
  // Before any citation is opened, the policy's own document.
  const viewedDocumentId = activeProvenance?.document_id ?? policy.data?.source_document_id ?? null;
  const viewedFile = useDocumentFile(viewedDocumentId);

  function ask(text: string) {
    if (!text.trim() || !id) return;
    askMutation.mutate(
      { question: text },
      { onSuccess: (job) => setSearchParams({ q: job.job_id }) },
    );
  }

  function openCitation(citation: Citation) {
    if (citation.provenance) setActiveProvenance(citation.provenance);
  }

  const answering = jobQuery.data && jobQuery.data.status !== "succeeded" && jobQuery.data.status !== "failed";

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <div className="flex min-w-0 flex-1 flex-col gap-6">
        <header>
          <h1 className="font-serif text-2xl font-semibold text-foreground">Ask about your policy</h1>
          {policy.data && <p className="text-sm text-muted-foreground">{productLabel(policy.data)}</p>}
        </header>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            ask(question);
          }}
          className="flex gap-2"
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask a question about your policy…"
            aria-label="Your question"
            className="w-full rounded border border-rule bg-card px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={askMutation.isPending || !question.trim()}
            className="inline-flex items-center gap-1.5 rounded bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            <Send className="size-4" aria-hidden="true" />
            Ask
          </button>
        </form>

        {/* The transcript fills the box; the user still presses Ask. */}
        <VoiceInput onTranscript={setQuestion} disabled={askMutation.isPending} />

        <div className="flex flex-wrap gap-2">
          {SUGGESTED_QUESTIONS.map((q) => (
            <button
              key={q}
              type="button"
              onClick={() => {
                setQuestion(q);
                ask(q);
              }}
              className="rounded-full border border-rule px-3 py-1 text-xs text-muted-foreground hover:bg-secondary"
            >
              {q}
            </button>
          ))}
        </div>

        {askMutation.isError && (
          <ErrorState message="We couldn't submit your question. Try again." onRetry={() => ask(question)} />
        )}

        {jobId && (jobQuery.isPending || answering) && (
          <div className="flex items-center gap-2 rounded border border-rule bg-card px-4 py-3">
            <Skeleton className="h-4 w-4 rounded-full" />
            <span className="text-sm text-muted-foreground">
              {jobQuery.timedOut ? "Still working — this is taking longer than usual." : "Reading your policy…"}
            </span>
          </div>
        )}

        {jobQuery.isError && <ErrorState message="We couldn't get an answer. Try again." onRetry={() => ask(question)} />}
        {jobQuery.data?.status === "failed" && (
          <ErrorState message={jobQuery.data.error ?? "We couldn't get an answer. Try again."} onRetry={() => ask(question)} />
        )}

        {jobQuery.data?.status === "succeeded" && jobQuery.data.result && (
          <section className="flex flex-col gap-3">
            {jobQuery.data.result.abstained ? (
              <AbstentionCard
                missingFact={jobQuery.data.result.missing_context ?? "Your policy documents don't answer this."}
                resolvingDocument="Your full policy wording document"
              />
            ) : (
              <>
                <CitedProse text={jobQuery.data.result.answer} citations={jobQuery.data.result.citations} onOpenCitation={openCitation} />
                {/* D-42: removed sentences are never shown, only counted. */}
                {jobQuery.data.result.verification.sentences_removed > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {jobQuery.data.result.verification.sentences_removed === 1
                      ? "1 statement was left out because we couldn't confirm it in your policy."
                      : `${jobQuery.data.result.verification.sentences_removed} statements were left out because we couldn't confirm them in your policy.`}
                  </p>
                )}
                <CitationList citations={jobQuery.data.result.citations} onOpenProvenance={openCitation} />
              </>
            )}
          </section>
        )}
      </div>

      <aside className="w-full shrink-0 lg:w-96">
        <DocumentViewer fileUrl={viewedFile.data?.url ?? null} activeProvenance={activeProvenance} className="sticky top-4" />
      </aside>
    </div>
  );
}
