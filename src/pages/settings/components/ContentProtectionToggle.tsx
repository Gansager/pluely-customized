import { Switch, Label, Header } from "@/components";
import { useApp } from "@/contexts";

interface ContentProtectionToggleProps {
  className?: string;
}

// Patch 19 — let the user opt out of content protection so Pluely shows up in
// screen shares / recordings (it's hidden from capture by default). Useful when
// you want to record or demo the assistant itself.
export const ContentProtectionToggle = ({
  className,
}: ContentProtectionToggleProps) => {
  const { customizable, toggleContentProtection } = useApp();
  const isProtected = customizable.contentProtection.isEnabled;

  const handleSwitchChange = async (checked: boolean) => {
    await toggleContentProtection(checked);
  };

  return (
    <div id="content-protection" className={`space-y-2 ${className}`}>
      <Header
        title="Hide from Screen Sharing"
        description="Control whether Pluely is hidden from screen capture and recordings"
        isMainTitle
      />
      <div className="flex items-center justify-between">
        <div className="flex items-center space-x-3">
          <div>
            <Label className="text-sm font-medium">
              {isProtected
                ? "Hidden from screen sharing"
                : "Visible in screen sharing"}
            </Label>
            <p className="text-xs text-muted-foreground mt-1">
              {isProtected
                ? "Pluely is invisible in screen shares & recordings (default)"
                : "Pluely appears in screen shares & recordings"}
            </p>
          </div>
        </div>
        <Switch
          checked={isProtected}
          onCheckedChange={handleSwitchChange}
          title={`Toggle to ${
            !isProtected ? "hidden" : "visible"
          } in screen sharing`}
          aria-label={`Toggle to ${
            isProtected ? "hidden" : "visible"
          } in screen sharing`}
        />
      </div>
    </div>
  );
};
