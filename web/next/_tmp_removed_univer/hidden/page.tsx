import { redirect } from 'next/navigation';

export default function TablesHiddenRedirect() {
  redirect('/tables?tab=hidden');
}
