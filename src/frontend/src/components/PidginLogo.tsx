import logoIcon from "../assets/logo-icon.jpg";

type PidginLogoProps = {
  size?: number;
  className?: string;
};

export function PidginLogo({ size = 30, className = "sidebar-logo" }: PidginLogoProps) {
  return (
    <img
      className={className}
      src={logoIcon}
      alt=""
      width={size}
      height={size}
      draggable={false}
    />
  );
}
