import { cva, type VariantProps } from "class-variance-authority";
import type { AnchorHTMLAttributes, ReactNode } from "react";
import { Link, type LinkProps } from "react-router-dom";

import { cn } from "@/lib/cn";

const linkButtonStyles = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-background transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)] focus-visible:ring-offset-2",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--color-primary)] text-[var(--color-primary-foreground)] hover:opacity-90",
        secondary:
          "bg-[var(--color-secondary)] text-[var(--color-secondary-foreground)] hover:opacity-90",
        outline:
          "border border-[var(--color-border)] bg-[var(--color-background)] hover:bg-[var(--color-accent)] hover:text-[var(--color-accent-foreground)]",
        ghost:
          "hover:bg-[var(--color-accent)] hover:text-[var(--color-accent-foreground)]",
      },
      size: {
        sm: "h-8 px-3 text-xs",
        md: "h-9 px-4",
        lg: "h-10 px-6",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

type Variants = VariantProps<typeof linkButtonStyles>;

interface InternalProps extends LinkProps, Variants {
  external?: false;
  children?: ReactNode;
  className?: string;
}

interface ExternalProps
  extends AnchorHTMLAttributes<HTMLAnchorElement>,
    Variants {
  external: true;
  to: string;
  children?: ReactNode;
}

type Props = InternalProps | ExternalProps;

export function LinkButton(props: Props) {
  const { variant, size, className } = props;
  const classes = cn(linkButtonStyles({ variant, size }), className);

  if (props.external) {
    const { external: _ext, to, ...rest } = props;
    void _ext;
    return (
      <a {...rest} href={to} className={classes} rel="noreferrer noopener" target="_blank">
        {props.children}
      </a>
    );
  }
  const { external: _ext, ...rest } = props;
  void _ext;
  return <Link {...rest} className={classes} />;
}
