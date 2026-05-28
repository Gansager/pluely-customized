import { useCompletion } from "@/hooks";
import { Input } from "./Input";
import { SummarizeMeetingButton } from "../SummarizeMeetingButton";

export const Completion = ({ isHidden }: { isHidden: boolean }) => {
  const completion = useCompletion();

  return (
    <>
      <Input {...completion} isHidden={isHidden} />
      <SummarizeMeetingButton />
    </>
  );
};
