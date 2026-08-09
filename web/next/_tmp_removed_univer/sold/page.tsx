import { redirect } from 'next/navigation';

export default function TablesSoldRedirect() {
  redirect('/tables?tab=sold');
}
