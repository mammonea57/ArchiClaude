"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Loader2, MapPin } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { GeocodingResult } from "@/lib/types";

export interface ParcelSearchProps {
  onSelect: (result: GeocodingResult) => void;
}

export default function ParcelSearch({ onSelect }: ParcelSearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<GeocodingResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const search = useCallback(async (q: string) => {
    if (!q.trim() || q.length < 3) {
      setResults([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const data = await apiFetch<GeocodingResult[]>(
        `/parcels/search?q=${encodeURIComponent(q)}&limit=5`,
      );
      setResults(data);
      setOpen(data.length > 0);
    } catch {
      setResults([]);
      setOpen(false);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(query), 250);
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, search]);

  // Close dropdown on outside click
  useEffect(() => {
    function handleOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleOutside);
    return () => document.removeEventListener("mousedown", handleOutside);
  }, []);

  function handleSelect(result: GeocodingResult) {
    setQuery(result.label);
    setResults([]);
    setOpen(false);
    onSelect(result);
  }

  return (
    <div ref={containerRef} className="relative w-full">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Rechercher une adresse..."
          className="w-full rounded-lg border border-slate-200 bg-white px-4 py-2.5 pr-10 text-sm text-slate-900 placeholder:text-slate-400 shadow-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition"
          autoComplete="off"
        />
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 pointer-events-none">
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <MapPin className="h-4 w-4" />
          )}
        </span>
      </div>

      {open && results.length > 0 && (
        <ul className="absolute z-50 mt-1 w-full rounded-lg border border-slate-200 bg-white shadow-lg overflow-hidden">
          {results.map((result, i) => (
            <li key={`${result.label}-${i}`}>
              <button
                type="button"
                className="w-full text-left px-4 py-2.5 text-sm text-slate-800 hover:bg-teal-50 hover:text-teal-800 transition-colors flex flex-col gap-0.5"
                onClick={() => handleSelect(result)}
              >
                <span className="font-medium leading-tight">{result.label}</span>
                <span className="text-xs text-slate-400">{result.city}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
