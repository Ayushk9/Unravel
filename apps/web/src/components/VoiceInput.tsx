import { useEffect, useRef, useState } from "react";
import { Mic, Square } from "lucide-react";

/**
 * Speak a question instead of typing it, with the browser's own speech
 * recognition (the Web Speech API). No audio passes through our API: the
 * browser sends it to its own speech service, which is why the disclosure
 * line below is always shown next to the mic.
 *
 * The transcript only ever fills the question box. It is never submitted
 * automatically: the user reads it, edits it if the browser misheard, and
 * presses Ask. Devanagari digits ("१२,०००") become ASCII ("12,000"), the same
 * normalisation the server applies, so the number check reads them.
 *
 * Where the browser has no speech recognition (Firefox, most WebViews), the
 * component renders nothing and typing works as before.
 */

// TypeScript's DOM library declares the speech *events* but not the
// recognizer itself, so the few members used here are declared locally.
interface Recognizer {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognizerConstructor = new () => Recognizer;

function recognizerConstructor(): RecognizerConstructor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as { SpeechRecognition?: RecognizerConstructor; webkitSpeechRecognition?: RecognizerConstructor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

const LANGUAGES = [
  { code: "en-IN", label: "English" },
  { code: "hi-IN", label: "हिन्दी (Hindi)" },
  { code: "mr-IN", label: "मराठी (Marathi)" },
] as const;
type LanguageCode = (typeof LANGUAGES)[number]["code"];

const STORAGE_KEY = "unravel:voice-language";

function rememberedLanguage(): LanguageCode {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return LANGUAGES.some((l) => l.code === stored) ? (stored as LanguageCode) : "en-IN";
  } catch {
    return "en-IN"; // storage blocked (private window, etc.): fall back quietly
  }
}

function remember(code: LanguageCode) {
  try {
    localStorage.setItem(STORAGE_KEY, code);
  } catch {
    // Not remembered this time; voice input still works.
  }
}

const DEVANAGARI_DIGITS: Record<string, string> = { "०": "0", "१": "1", "२": "2", "३": "3", "४": "4", "५": "5", "६": "6", "७": "7", "८": "8", "९": "9" };

function asciiDigits(text: string): string {
  return text.replace(/[०-९]/g, (digit) => DEVANAGARI_DIGITS[digit] ?? digit);
}

const ERROR_MESSAGES: Record<string, string> = {
  "no-speech": "We didn't hear anything. Try again, or type your question.",
  "audio-capture": "No microphone was found. You can type your question instead.",
  "not-allowed": "Microphone access is blocked. Allow it in your browser's settings, or type your question.",
  "service-not-allowed": "Your browser isn't allowing speech recognition here. Type your question instead.",
  network: "Your browser's speech service couldn't be reached. Check your connection, or type your question.",
  "language-not-supported": "Your browser can't recognise speech in this language. Try another, or type your question.",
};

export interface VoiceInputProps {
  /** Called once with the final transcript. The caller puts it in the question box; nothing is submitted. */
  onTranscript: (text: string) => void;
  disabled?: boolean;
}

export function VoiceInput({ onTranscript, disabled = false }: VoiceInputProps) {
  const [Constructor] = useState(recognizerConstructor);
  const [language, setLanguage] = useState<LanguageCode>(rememberedLanguage);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recognizer = useRef<Recognizer | null>(null);

  // Stop listening if the page is left mid-sentence.
  useEffect(() => () => recognizer.current?.abort(), []);

  if (!Constructor) return null;

  function start() {
    if (!Constructor) return;
    setError(null);
    setInterim("");
    const r = new Constructor();
    r.lang = language;
    r.interimResults = true; // show words as they are recognised
    r.continuous = false; // one question, then stop
    r.maxAlternatives = 1;
    r.onresult = (event) => {
      let finalText = "";
      let partial = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const transcript = result?.[0]?.transcript ?? "";
        if (result?.isFinal) finalText += transcript;
        else partial += transcript;
      }
      setInterim(asciiDigits(partial));
      if (finalText.trim()) onTranscript(asciiDigits(finalText.trim()));
    };
    r.onerror = (event) => {
      // "aborted" is our own stop(); not an error to show.
      if (event.error !== "aborted") setError(ERROR_MESSAGES[event.error] ?? "Voice input stopped. You can type your question instead.");
    };
    r.onend = () => {
      setListening(false);
      setInterim("");
    };
    recognizer.current = r;
    try {
      r.start();
      setListening(true);
    } catch {
      setError("Voice input couldn't start. You can type your question instead.");
    }
  }

  function stop() {
    recognizer.current?.stop();
  }

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={listening ? stop : start}
          disabled={disabled}
          aria-pressed={listening}
          aria-label={listening ? "Stop listening" : "Speak your question"}
          className={`inline-flex items-center gap-1.5 rounded border px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${
            listening ? "border-flag text-flag" : "border-rule text-foreground hover:bg-secondary"
          }`}
        >
          {listening ? <Square className="size-4" aria-hidden="true" /> : <Mic className="size-4" aria-hidden="true" />}
          {listening ? "Stop" : "Speak"}
        </button>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          Language
          <select
            value={language}
            disabled={listening}
            onChange={(e) => {
              const code = e.target.value as LanguageCode;
              setLanguage(code);
              remember(code);
            }}
            className="rounded border border-rule bg-background px-1.5 py-1 text-xs"
          >
            {LANGUAGES.map((l) => (
              <option key={l.code} value={l.code}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        {listening && (
          <span role="status" className="text-xs text-flag">
            Listening…
          </span>
        )}
      </div>
      {listening && interim && <p className="text-sm italic text-muted-foreground">{interim}</p>}
      <p className="text-xs text-muted-foreground">Voice is converted to text by your browser's speech service.</p>
      {error && <p className="text-xs text-flag">{error}</p>}
    </div>
  );
}
