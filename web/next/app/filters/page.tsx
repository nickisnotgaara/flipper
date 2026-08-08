'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Card,
  CardBody,
  Button,
  Input,
  Select,
  SelectItem,
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
  useDisclosure,
  Chip,
  Spinner,
} from '@heroui/react';
import { Bookmark, Plus, Trash2, ExternalLink, Save } from 'lucide-react';

const schema = z.object({
  name: z.string().min(2, 'Минимум 2 символа').max(80),
  table: z.enum(['active', 'sold', 'hidden', 'houses']),
});
type FormValues = z.infer<typeof schema>;

const FALLBACK: any[] = [
  { id: 1, name: '1к до 12М в ЦАО', table: 'active', filters: { rooms: '1', price_max: '12000000' }, created_at: '2026-08-08T12:00:00' },
  { id: 2, name: 'С ремонтом, с фото', table: 'active', filters: { has_renovation: 'true' }, created_at: '2026-08-08T12:30:00' },
];

export default function FiltersPage() {
  const { isOpen, onOpen, onClose } = useDisclosure();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['saved-filters'],
    queryFn: async () => {
      try {
        const r = await fetch('http://127.0.0.1:8001/api/saved-filters', { cache: 'no-store' });
        if (!r.ok) throw new Error('bad');
        return await r.json();
      } catch {
        return FALLBACK;
      }
    },
  });

  const { register, handleSubmit, formState: { errors, isSubmitting }, reset, watch, setValue } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: '', table: 'active' },
  });

  const create = useMutation({
    mutationFn: async (input: FormValues) => {
      const r = await fetch('http://127.0.0.1:8001/api/saved-filters', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...input, filters: {} }),
      });
      if (!r.ok) throw new Error('save failed');
      return await r.json();
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['saved-filters'] });
      onClose();
      reset();
    },
  });

  const remove = useMutation({
    mutationFn: async (id: number) => {
      await fetch(`http://127.0.0.1:8001/api/saved-filters/${id}`, { method: 'DELETE' });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['saved-filters'] }),
  });

  return (
    <div className="space-y-6">
      <div className="flex items-start gap-4">
        <div>
          <h1 className="text-[22px] font-bold tracking-tight">Сохранённые фильтры</h1>
          <p className="text-[13px] text-zinc-500 mt-0.5">
            Преset'ы фильтров таблиц · react-hook-form + zod валидация
          </p>
        </div>
        <div className="flex-1" />
        <Button
          color="default"
          size="sm"
          startContent={<Plus size={14} />}
          onPress={onOpen}
          className="bg-zinc-900 text-white data-[hover=true]:bg-zinc-800"
        >
          Новый фильтр
        </Button>
      </div>

      <Card shadow="none" className="border border-zinc-200 rounded-2xl">
        <CardBody className="p-0">
          {isLoading ? (
            <div className="text-center py-12 text-zinc-500"><Spinner size="sm" /> Загрузка…</div>
          ) : (
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-zinc-200 bg-zinc-50">
                  <th className="text-left px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-zinc-500">Имя</th>
                  <th className="text-left px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-zinc-500">Таблица</th>
                  <th className="text-left px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-zinc-500">Фильтры</th>
                  <th className="text-left px-4 py-2.5 font-semibold text-[11px] uppercase tracking-wider text-zinc-500">Создан</th>
                  <th className="px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {(data ?? FALLBACK).map((f: any) => (
                  <tr key={f.id} className="border-b border-zinc-100 hover:bg-zinc-50">
                    <td className="px-4 py-3 font-medium text-zinc-900">{f.name}</td>
                    <td className="px-4 py-3">
                      <Chip size="sm" variant="flat" classNames={{ base: 'h-5 px-1.5' }}>
                        <span className="text-[10px] uppercase font-semibold tracking-wider">{f.table}</span>
                      </Chip>
                    </td>
                    <td className="px-4 py-3 text-zinc-600 text-[12px] font-mono">
                      {Object.entries(f.filters || {}).map(([k, v]) => `${k}=${v}`).join(', ') || '—'}
                    </td>
                    <td className="px-4 py-3 text-zinc-500 text-[12px]">
                      {new Date(f.created_at).toLocaleString('ru-RU')}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-1">
                        <Button isIconOnly size="sm" variant="light" className="text-zinc-500">
                          <ExternalLink size={14} />
                        </Button>
                        <Button
                          isIconOnly
                          size="sm"
                          variant="light"
                          className="text-rose-500 data-[hover=true]:text-rose-700"
                          onPress={() => remove.mutate(f.id)}
                        >
                          <Trash2 size={14} />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardBody>
      </Card>

      <Modal isOpen={isOpen} onClose={onClose} size="md" backdrop="opaque">
        <ModalContent>
          <form onSubmit={handleSubmit((v) => create.mutate(v))}>
            <ModalHeader className="flex items-center gap-2">
              <Bookmark size={18} className="text-emerald-600" />
              <span>Новый сохранённый фильтр</span>
            </ModalHeader>
            <ModalBody className="space-y-3">
              <div>
                <label className="text-[12px] text-zinc-600 font-medium block mb-1">Имя</label>
                <Input
                  size="sm"
                  variant="flat"
                  placeholder="Например: 1к до 12М в ЦАО"
                  value={watch('name')}
                  onValueChange={(v) => setValue('name', v, { shouldValidate: true })}
                  isInvalid={!!errors.name}
                  errorMessage={errors.name?.message}
                  classNames={{ inputWrapper: 'bg-zinc-100 data-[hover=true]:bg-zinc-50' }}
                />
              </div>
              <div>
                <label className="text-[12px] text-zinc-600 font-medium block mb-1">Таблица</label>
                <Select
                  size="sm"
                  variant="flat"
                  selectedKeys={new Set([watch('table')])}
                  onSelectionChange={(keys) => {
                    const v = Array.from(keys as Set<string>)[0];
                    if (v) setValue('table', v as any, { shouldValidate: true });
                  }}
                  classNames={{ trigger: 'h-8 min-h-8 bg-zinc-100 data-[hover=true]:bg-zinc-50' }}
                >
                  <SelectItem key="active">Активные</SelectItem>
                  <SelectItem key="sold">Снято</SelectItem>
                  <SelectItem key="hidden">Скрытые</SelectItem>
                  <SelectItem key="houses">Дома</SelectItem>
                </Select>
              </div>
            </ModalBody>
            <ModalFooter>
              <Button variant="light" onPress={onClose}>Отмена</Button>
              <Button
                type="submit"
                color="default"
                isLoading={isSubmitting || create.isPending}
                startContent={<Save size={14} />}
                className="bg-zinc-900 text-white data-[hover=true]:bg-zinc-800"
              >
                Сохранить
              </Button>
            </ModalFooter>
          </form>
        </ModalContent>
      </Modal>
    </div>
  );
}
