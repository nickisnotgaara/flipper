import { redirect } from 'next/navigation';

export default function TablesHousesRedirect() {
  redirect('/tables?tab=houses');
}
