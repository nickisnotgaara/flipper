'use client';

import { Construction } from 'lucide-react';
import { Card, CardBody, Chip } from '@heroui/react';
import type { LucideIcon } from 'lucide-react';

export default function PlaceholderPage({
  title,
  description,
  icon: Icon = Construction,
  features,
}: {
  title: string;
  description: string;
  icon?: LucideIcon;
  features?: string[];
}) {
  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        <div>
          <h1 className="text-[22px] font-bold tracking-tight">{title}</h1>
          <p className="text-[13px] text-zinc-500 mt-0.5">{description}</p>
        </div>
      </div>

      <Card shadow="none" className="border border-zinc-200 border-dashed rounded-2xl">
        <CardBody className="p-12 text-center">
          <div className="inline-flex w-12 h-12 rounded-2xl bg-zinc-100 text-zinc-500 items-center justify-center mb-3">
            <Icon size={24} />
          </div>
          <div className="text-[15px] font-semibold">Скоро</div>
          <div className="text-[13px] text-zinc-500 mt-1">
            Эта секция появится в одном из следующих релизов
          </div>

          {features && features.length > 0 && (
            <div className="mt-6 text-left max-w-md mx-auto">
              <div className="text-[11px] uppercase tracking-wider text-zinc-400 font-semibold mb-2">
                В этом разделе будет
              </div>
              <ul className="space-y-1.5">
                {features.map((f, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 text-[13px] text-zinc-700"
                  >
                    <span className="w-1 h-1 rounded-full bg-zinc-400 mt-2 shrink-0" />
                    <span>{f}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {features && features.length > 0 && (
            <div className="mt-6 flex flex-wrap justify-center gap-2">
              {features.slice(0, 3).map((_, i) => (
                <Chip key={i} size="sm" variant="flat" color="default">
                  Phase {4 + i}
                </Chip>
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
