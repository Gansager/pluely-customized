import { UseCompletionReturn } from "@/types";
import { Input } from "./Input";
import { SummarizeMeetingButton } from "../SummarizeMeetingButton";

// Patch 14: Screenshot moved out of this component (now rendered in
// app/index.tsx, third-from-left on the panel). Completion now receives
// the shared useCompletion state via props instead of owning it, so
// app/index.tsx can render Screenshot from the same state bag.
export const Completion = ({
  completion,
  isHidden,
}: {
  completion: UseCompletionReturn;
  isHidden: boolean;
}) => {
  return (
    <>
      <Input {...completion} isHidden={isHidden} />
      <SummarizeMeetingButton />
    </>
  );
};
