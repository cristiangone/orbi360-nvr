import { cn } from "@/lib/utils";
import logoUrl from "../../images/branding/orbi360-symbol.png";

type LogoProps = {
  className?: string;
};
export default function Logo({ className }: LogoProps) {
  return (
    <img
      src={logoUrl}
      alt="Orbi360 NVR"
      draggable={false}
      className={cn("object-contain", className)}
    />
  );
}
