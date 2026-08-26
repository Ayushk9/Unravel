import type { Insurer } from "@/api/types";
import { ids } from "./ids";

/**
 * Fictional insurer names, deliberately not real Indian insurers. The
 * benchmarking feature attaches fabricated performance figures to these —
 * doing that under a real company's name would misrepresent real regulator
 * data even inside a mock, which is exactly the dishonesty this project's
 * product-integrity rules exist to prevent.
 */
export const insurers: Insurer[] = [
  { id: ids.insurer.group, name: "Kavach Health Assurance", irdai_code: "IRDAI-KHA-014" },
  { id: ids.insurer.retail, name: "Suraksha General Insurance", irdai_code: "IRDAI-SGI-027" },
  { id: ids.insurer.bench3, name: "Nirvaan Health Insurance", irdai_code: "IRDAI-NHI-033" },
  { id: ids.insurer.bench4, name: "Bharosa General Insurance", irdai_code: "IRDAI-BGI-041" },
  { id: ids.insurer.bench5, name: "Sanjeevani Health Insurance", irdai_code: "IRDAI-SHI-052" },
  { id: ids.insurer.bench6, name: "Rakshak General Insurance", irdai_code: "IRDAI-RGI-059" },
  { id: ids.insurer.bench7, name: "Arogya Mitra Insurance", irdai_code: "IRDAI-AMI-063" },
  { id: ids.insurer.bench8, name: "Vishwas General Insurance", irdai_code: "IRDAI-VGI-071" },
  { id: ids.insurer.bench9, name: "Shubham Health Insurance", irdai_code: null },
  { id: ids.insurer.bench10, name: "Poorna Suraksha Insurance", irdai_code: null },
];

export function insurerById(id: string): Insurer {
  const insurer = insurers.find((i) => i.id === id);
  if (!insurer) throw new Error(`fixture bug: unknown insurer id ${id}`);
  return insurer;
}
