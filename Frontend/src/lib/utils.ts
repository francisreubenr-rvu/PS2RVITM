import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

// Class-name helper the shadcn-style registry components import as "@/lib/utils".
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
