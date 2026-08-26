import type { Member } from "@/api/types";
import { ids } from "./ids";

export const members: Member[] = [
  { id: ids.member.self, full_name: "Ananya Rao", relationship: "self", date_of_birth: "1990-02-14" },
  { id: ids.member.spouse, full_name: "Vikram Rao", relationship: "spouse", date_of_birth: "1988-11-02" },
  { id: ids.member.child, full_name: "Ishaan Rao", relationship: "child", date_of_birth: "2019-06-30" },
  { id: ids.member.parent, full_name: "Lakshmi Rao", relationship: "parent", date_of_birth: "1962-09-18" },
];

export function memberById(id: string): Member {
  const member = members.find((m) => m.id === id);
  if (!member) throw new Error(`fixture bug: unknown member id ${id}`);
  return member;
}
