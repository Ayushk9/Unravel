import { healthHandlers } from "./health";
import { jobsHandlers } from "./jobs";
import { documentsHandlers } from "./documents";
import { policiesHandlers } from "./policies";
import { membersHandlers } from "./members";
import { householdHandlers } from "./household";
import { claimsHandlers } from "./claims";
import { alertsHandlers } from "./alerts";
import { insurersHandlers } from "./insurers";
import { ombudsmanHandlers } from "./ombudsman";

export const handlers = [
  ...healthHandlers,
  ...jobsHandlers,
  ...documentsHandlers,
  ...policiesHandlers,
  ...membersHandlers,
  ...householdHandlers,
  ...claimsHandlers,
  ...alertsHandlers,
  ...insurersHandlers,
  ...ombudsmanHandlers,
];
