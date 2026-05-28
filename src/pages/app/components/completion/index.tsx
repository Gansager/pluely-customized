import { useCompletion } from "@/hooks";
import { Audio } from "./Audio";
import { Input } from "./Input";
import { SummarizeMeetingButton } from "../SummarizeMeetingButton";

export const Completion = ({ isHidden }: { isHidden: boolean }) => {
  const completion = useCompletion();

  return (
    <>
      <Audio {...completion} />
      <Input {...completion} isHidden={isHidden} />
      <SummarizeMeetingButton />
    </>
  );
};
