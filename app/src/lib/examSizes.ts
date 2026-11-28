/** The size choices: about a quarter, half and three quarters of the questions there are, and all of them. None is
 * under 3 or over what there is: 6 questions give «۳» and «همه‌ی ۶»; 12 give 3, 6, 9 and «همه‌ی ۱۲»; 2 give «همه‌ی ۲». */
export function examSizes(pool: number): number[] {
  if (pool <= 0) return [];
  const parts = [0.25, 0.5, 0.75].map((f) => Math.round(pool * f)).filter((n) => n >= 3 && n <= pool - 2); // «۵» beside «همه‌ی ۶» would be no real choice
  return [...new Set(parts), pool];
}
