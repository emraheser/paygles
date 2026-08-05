import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { api } from "../lib/api";
import { motion, AnimatePresence } from "framer-motion";
import { Bell, Clock, Flame, TrendingUp, Filter, ChevronDown, Search, Send, Trash2, ShoppingBag } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { tr } from "date-fns/locale";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "../components/ui/dialog";

interface Topic {
    id: number;
    site_name: string;
    title: string;
    url: string;
    deal_url: string | null;
    clean_deal_url: string | null;
    deal_title: string | null;
    deal_price: string | null;
    akakce_url: string;
    notification_sent: boolean;
    domain_skipped: boolean;
    source_date: string | null;
    scraped_at: string;
}

interface SyncStatus {
    last_scrape_completed_at: string | null;
    scrape_interval_minutes: number;
}

const SYNC_STATUS_POLL_MS = 5000;

/** Play a short attention beep using Web Audio API — no external file needed. */
const playNotifSound = () => {
    try {
        const ctx = new AudioContext();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = "sine";
        // Two-tone chime: 880Hz then 1174Hz
        osc.frequency.setValueAtTime(880, ctx.currentTime);
        osc.frequency.setValueAtTime(1174, ctx.currentTime + 0.12);
        gain.gain.setValueAtTime(0.18, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.35);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + 0.35);
    } catch {
        // AudioContext not available — silently skip.
    }
};

const parseApiDateToLocal = (value: string) => {
    // Backend returns naive UTC datetime strings; force UTC parsing.
    const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
    return new Date(normalized);
};

const getTopicDate = (topic: Topic) => parseApiDateToLocal(topic.source_date || topic.scraped_at);

const STORE_LABELS: Record<string, { label: string; color: string }> = {
    hepsiburada: { label: "Hepsiburada", color: "border-orange-300 bg-orange-50 text-orange-700 dark:border-orange-400/30 dark:bg-orange-500/10 dark:text-orange-300" },
    trendyol: { label: "Trendyol", color: "border-orange-300 bg-orange-50 text-orange-700 dark:border-orange-400/30 dark:bg-orange-500/10 dark:text-orange-300" },
    amazon: { label: "Amazon", color: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-300" },
    n11: { label: "N11", color: "border-purple-300 bg-purple-50 text-purple-700 dark:border-purple-400/30 dark:bg-purple-500/10 dark:text-purple-300" },
    teknosa: { label: "Teknosa", color: "border-red-300 bg-red-50 text-red-700 dark:border-red-400/30 dark:bg-red-500/10 dark:text-red-300" },
    mediamarkt: { label: "MediaMarkt", color: "border-red-300 bg-red-50 text-red-700 dark:border-red-400/30 dark:bg-red-500/10 dark:text-red-300" },
    a101: { label: "A101", color: "border-blue-300 bg-blue-50 text-blue-700 dark:border-blue-400/30 dark:bg-blue-500/10 dark:text-blue-300" },
    bim: { label: "BİM", color: "border-red-300 bg-red-50 text-red-700 dark:border-red-400/30 dark:bg-red-500/10 dark:text-red-300" },
    vatan: { label: "Vatan", color: "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-400/30 dark:bg-emerald-500/10 dark:text-emerald-300" },
    migros: { label: "Migros", color: "border-orange-300 bg-orange-50 text-orange-700 dark:border-orange-400/30 dark:bg-orange-500/10 dark:text-orange-300" },
    gratis: { label: "Gratis", color: "border-pink-300 bg-pink-50 text-pink-700 dark:border-pink-400/30 dark:bg-pink-500/10 dark:text-pink-300" },
    pttavm: { label: "PttAVM", color: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-300" },
    ciceksepeti: { label: "Çiçeksepeti", color: "border-pink-300 bg-pink-50 text-pink-700 dark:border-pink-400/30 dark:bg-pink-500/10 dark:text-pink-300" },
    gittigidiyor: { label: "GittiGidiyor", color: "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-300" },
    letgo: { label: "Letgo", color: "border-teal-300 bg-teal-50 text-teal-700 dark:border-teal-400/30 dark:bg-teal-500/10 dark:text-teal-300" },
    aliexpress: { label: "AliExpress", color: "border-red-300 bg-red-50 text-red-700 dark:border-red-400/30 dark:bg-red-500/10 dark:text-red-300" },
    idefix: { label: "İdefix", color: "border-purple-300 bg-purple-50 text-purple-700 dark:border-purple-400/30 dark:bg-purple-500/10 dark:text-purple-300" },
};

const getStoreBadge = (topic: Topic): { label: string; color: string } | null => {
    const url = topic.clean_deal_url || topic.deal_url;
    if (!url) return null;
    try {
        const hostname = new URL(url).hostname.toLowerCase();
        for (const [key, value] of Object.entries(STORE_LABELS)) {
            if (hostname.includes(key)) return value;
        }
    } catch { /* ignore invalid URLs */ }
    return null;
};

export function Dashboard() {
    const [topics, setTopics] = useState<Topic[]>([]);
    const [loading, setLoading] = useState(true);
    const [selectedSite, setSelectedSite] = useState("TUMU");
    const [showOlder, setShowOlder] = useState(false);
    const [sendingId, setSendingId] = useState<number | null>(null);
    const [deletingId, setDeletingId] = useState<number | null>(null);
    const [sendDialogOpen, setSendDialogOpen] = useState(false);
    const [sendTopic, setSendTopic] = useState<Topic | null>(null);
    const [sendTitle, setSendTitle] = useState("");
    const [sendLink, setSendLink] = useState("");
    const lastScrapeCompletedRef = useRef<string | null>(null);
    const knownTopicIdsRef = useRef<Set<number> | null>(null);
    const [notifPermission, setNotifPermission] = useState<NotificationPermission>(
        typeof Notification !== "undefined" ? Notification.permission : "denied"
    );

    const openSendDialog = (e: React.MouseEvent, topic: Topic) => {
        e.preventDefault();
        e.stopPropagation();
        setSendTopic(topic);
        setSendTitle(topic.deal_title || topic.title);
        setSendLink(topic.clean_deal_url || topic.deal_url || topic.url);
        setSendDialogOpen(true);
    };

    const handleForceSend = async () => {
        if (!sendTopic) {
            return;
        }
        setSendingId(sendTopic.id);
        try {
            await api.post(`/dashboard/topics/${sendTopic.id}/send`, {
                title: sendTitle,
                link: sendLink,
            });
            setTopics(prev => prev.map(t => t.id === sendTopic.id ? { ...t, notification_sent: true, domain_skipped: false } : t));
            setSendDialogOpen(false);
        } catch {
            alert("Gönderilemedi.");
        } finally {
            setSendingId(null);
        }
    };

    const handleDeleteTopic = async (e: React.MouseEvent, topicId: number) => {
        e.preventDefault();
        e.stopPropagation();
        if (!confirm("Bu kaydı silmek istediğine emin misin?")) {
            return;
        }
        setDeletingId(topicId);
        try {
            await api.delete(`/dashboard/topics/${topicId}`);
            setTopics(prev => prev.filter(t => t.id !== topicId));
        } catch {
            alert("Silinemedi.");
        } finally {
            setDeletingId(null);
        }
    };

    const handleOpenAkakce = (e: React.MouseEvent, akakceUrl: string) => {
        e.preventDefault();
        e.stopPropagation();
        window.open(akakceUrl, "_blank", "noopener,noreferrer");
    };

    const requestNotifPermission = useCallback(async () => {
        if (typeof Notification === "undefined") return;
        if (Notification.permission === "default") {
            const result = await Notification.requestPermission();
            setNotifPermission(result);
        }
    }, []);

    const notifyNewTopics = useCallback((newTopics: Topic[]) => {
        // Always play sound regardless of Notification permission
        if (newTopics.length > 0) {
            playNotifSound();
        }
        if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
        for (const topic of newTopics) {
            const title = topic.deal_title || topic.title;
            const price = topic.deal_price ? ` — ${topic.deal_price} TL` : "";
            new Notification(`🔥 ${topic.site_name}`, {
                body: `${title}${price}`,
                icon: "/favicon.ico",
                tag: `topic-${topic.id}`,
            });
        }
    }, []);

    const fetchTopics = useCallback(async () => {
        try {
            const data = await api.get<Topic[]>("/dashboard/topics");
            // Detect genuinely new topics (not on first load)
            if (knownTopicIdsRef.current !== null) {
                const prev = knownTopicIdsRef.current;
                const brandNew = data.filter(t => !prev.has(t.id));
                if (brandNew.length > 0) {
                    notifyNewTopics(brandNew);
                }
            }
            knownTopicIdsRef.current = new Set(data.map(t => t.id));
            setTopics(data);
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    }, [notifyNewTopics]);

    const fetchSyncStatus = useCallback(async () => {
        try {
            const status = await api.get<SyncStatus>("/dashboard/sync-status");
            const lastCompletedAt = status.last_scrape_completed_at;
            if (!lastCompletedAt) {
                return;
            }
            if (!lastScrapeCompletedRef.current) {
                lastScrapeCompletedRef.current = lastCompletedAt;
                return;
            }
            if (lastScrapeCompletedRef.current !== lastCompletedAt) {
                lastScrapeCompletedRef.current = lastCompletedAt;
                await fetchTopics();
            }
        } catch (e) {
            console.error(e);
        }
    }, [fetchTopics]);

    useEffect(() => {
        let cancelled = false;

        const bootstrap = async () => {
            try {
                const status = await api.get<SyncStatus>("/dashboard/sync-status");
                if (!cancelled) {
                    lastScrapeCompletedRef.current = status.last_scrape_completed_at;
                }
            } catch (e) {
                console.error(e);
            } finally {
                if (!cancelled) {
                    await fetchTopics();
                }
            }
        };

        void requestNotifPermission();
        void bootstrap();
        const interval = setInterval(() => {
            void fetchSyncStatus();
        }, SYNC_STATUS_POLL_MS);
        return () => {
            cancelled = true;
            clearInterval(interval);
        };
    }, [fetchTopics, fetchSyncStatus, requestNotifPermission]);

    const siteOptions = useMemo(() => {
        const unique = Array.from(new Set(topics.map((topic) => topic.site_name)));
        return ["TUMU", ...unique];
    }, [topics]);

    const visibleTopics = useMemo(() => {
        if (selectedSite === "TUMU") {
            return topics;
        }
        return topics.filter((topic) => topic.site_name === selectedSite);
    }, [topics, selectedSite]);

    const [recentTopics, olderTopics] = useMemo(() => {
        const now = Date.now();
        const oneHourMs = 1 * 60 * 60 * 1000;
        const recent: Topic[] = [];
        const older: Topic[] = [];

        for (const topic of visibleTopics) {
            const topicTime = parseApiDateToLocal(topic.source_date || topic.scraped_at).getTime();
            if (now - topicTime <= oneHourMs) {
                recent.push(topic);
            } else {
                older.push(topic);
            }
        }
        return [recent, older];
    }, [visibleTopics]);

    if (loading) {
        return (
            <div className="flex justify-center items-center h-[60vh]">
                <div className="flex flex-col items-center gap-4">
                    <div className="w-12 h-12 rounded-full border-[3px] border-indigo-500/30 border-t-indigo-500 animate-spin" />
                    <p className="text-sm text-stone-500 dark:text-slate-400">Fırsatlar yükleniyor...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="dashboard-theme space-y-6 pb-10">
            <div>
                <h1 className="hero-title section-hero-title text-[#102a43] dark:text-slate-100">
                    Güncel fırsatlar
                </h1>
            </div>

            <div className="surface-panel rounded-2xl p-3 space-y-2.5">
                <div className="flex items-center gap-2 text-sm text-stone-700 dark:text-slate-200">
                    <Filter className="w-4 h-4 text-cyan-600 dark:text-cyan-300" />
                    Kaynak Filtresi
                </div>
                <div className="flex flex-wrap gap-2">
                    {siteOptions.map((site) => (
                        <button
                            key={site}
                            type="button"
                            onClick={() => setSelectedSite(site)}
                            className={`h-8 rounded-full px-3 text-xs font-medium transition ${
                                selectedSite === site
                                    ? "bg-[#102a43] text-white"
                                    : "border border-stone-300 bg-white text-stone-700 hover:border-stone-500 dark:border-slate-600 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:border-slate-400"
                            }`}
                        >
                            {site === "TUMU" ? "Tümü" : site}
                        </button>
                    ))}
                </div>
            </div>

            <div className="flex gap-3">
                <div className="flex items-center gap-2 rounded-xl border border-stone-300 bg-white px-3 py-2 dark:border-slate-600 dark:bg-slate-900/70">
                    <TrendingUp className="w-4 h-4 text-cyan-600 dark:text-cyan-300" />
                    <span className="text-xs font-medium text-stone-700 dark:text-slate-200">{visibleTopics.length} fırsat</span>
                </div>
                {notifPermission !== "granted" && typeof Notification !== "undefined" && (
                    <button
                        type="button"
                        onClick={requestNotifPermission}
                        className="flex items-center gap-2 rounded-xl border border-stone-300 bg-white px-3 py-2 transition-all hover:border-cyan-400 dark:border-slate-600 dark:bg-slate-900/70 dark:hover:border-cyan-400/60"
                    >
                        <Bell className="w-4 h-4 text-cyan-600 dark:text-cyan-300" />
                        <span className="text-xs font-medium text-stone-700 dark:text-slate-200">Bildirimleri Aç</span>
                    </button>
                )}
            </div>

            {/* Recent Grid */}
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                <AnimatePresence>
                    {recentTopics.map((topic, index) => {
                        const topicDate = getTopicDate(topic);
                        const storeBadge = getStoreBadge(topic);
                        return (
                        <motion.a
                            key={topic.id}
                            href={topic.clean_deal_url || topic.deal_url || topic.url}
                            target="_blank"
                            rel="noreferrer"
                            initial={{ opacity: 0, y: 16 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: index * 0.04, duration: 0.35, ease: "easeOut" }}
                            className="group relative deal-card-pro rounded-2xl p-4 transition-all duration-300 cursor-pointer"
                        >
                            {/* Source badge + store badge + time */}
                            <div className="flex items-center justify-between mb-2.5">
                                <div className="flex items-center gap-2">
                                    <span className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-2.5 py-1 text-[0.7rem] font-semibold uppercase tracking-wider text-amber-700 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-300">
                                        <Flame className="w-3 h-3" />
                                        {topic.site_name}
                                    </span>
                                    {storeBadge && (
                                        <span className={`inline-flex items-center gap-1 text-[0.65rem] font-medium px-2 py-1 rounded-md border ${storeBadge.color}`}>
                                            <ShoppingBag className="w-3 h-3" />
                                            {storeBadge.label}
                                        </span>
                                    )}
                                    {(!topic.notification_sent || topic.domain_skipped) && (
                                        <span className="inline-flex items-center gap-1 rounded-md border border-rose-300 bg-rose-50 px-2 py-1 text-[0.65rem] font-medium text-rose-700 dark:border-rose-400/30 dark:bg-rose-500/10 dark:text-rose-300">
                                            Gönderilmedi
                                        </span>
                                    )}
                                </div>
                                <span className="flex items-center gap-1 text-[0.7rem] text-stone-500 dark:text-slate-400">
                                    <Clock className="w-3 h-3" />
                                    {formatDistanceToNow(topicDate, { addSuffix: true, locale: tr })}
                                </span>
                            </div>

                            {/* Title */}
                            <h3 className="line-clamp-2 text-[0.9rem] font-medium leading-snug text-stone-900 transition-colors group-hover:text-black dark:text-slate-100 dark:group-hover:text-white">
                                {topic.deal_title || topic.title}
                            </h3>
                            {topic.deal_title && topic.deal_title !== topic.title && (
                                <p className="mt-0.5 line-clamp-1 text-[0.7rem] text-stone-500 dark:text-slate-400">{topic.title}</p>
                            )}

                            <div className="mt-2 flex items-center justify-between gap-2">
                                {topic.deal_price ? (
                                    <span className="inline-flex items-center rounded-md border border-emerald-300 bg-emerald-50 px-2 py-1 text-[0.7rem] font-semibold text-emerald-700 dark:border-emerald-400/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                                        {topic.deal_price}
                                    </span>
                                ) : (
                                    <span />
                                )}
                                    <div className="flex justify-end gap-2">
                                        <button
                                            type="button"
                                            onClick={(e) => handleOpenAkakce(e, topic.akakce_url)}
                                            className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-[0.65rem] font-medium text-amber-700 transition-all hover:bg-amber-100 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-300 dark:hover:bg-amber-500/20"
                                            title="Akakçe'de ara"
                                        >
                                            <Search className="w-3 h-3" />
                                            Akakçe
                                        </button>
                                        {(!topic.notification_sent || topic.domain_skipped) && (
                                            <button
                                                type="button"
                                                onClick={(e) => openSendDialog(e, topic)}
                                                disabled={sendingId === topic.id}
                                                className="inline-flex items-center gap-1 rounded-md border border-cyan-300 bg-cyan-50 px-2 py-1 text-[0.65rem] font-medium text-cyan-700 transition-all hover:bg-cyan-100 dark:border-cyan-400/30 dark:bg-cyan-500/10 dark:text-cyan-300 dark:hover:bg-cyan-500/20"
                                                title="Telegram'a gönder"
                                            >
                                                <Send className="w-3 h-3" />
                                                {sendingId === topic.id ? "..." : "Gönder"}
                                            </button>
                                        )}
                                        <button
                                            type="button"
                                            onClick={(e) => handleDeleteTopic(e, topic.id)}
                                            disabled={deletingId === topic.id}
                                            className="inline-flex items-center gap-1 rounded-md border border-rose-300 bg-rose-50 px-2 py-1 text-[0.65rem] font-medium text-rose-700 transition-all hover:bg-rose-100 dark:border-rose-400/30 dark:bg-rose-500/10 dark:text-rose-300 dark:hover:bg-rose-500/20"
                                            title="Kaydı sil"
                                        >
                                            <Trash2 className="w-3 h-3" />
                                            {deletingId === topic.id ? "..." : "Sil"}
                                        </button>
                                    </div>
                            </div>
                        </motion.a>
                        );
                    })}
                </AnimatePresence>
            </div>

            {olderTopics.length > 0 && (
                <div className="surface-panel rounded-2xl p-3 space-y-3">
                    <button
                        type="button"
                        onClick={() => setShowOlder((prev) => !prev)}
                        className="w-full flex items-center justify-between text-left"
                    >
                        <span className="text-sm font-medium text-stone-700 dark:text-slate-200">
                            1 saatten eski kayıtlar ({olderTopics.length})
                        </span>
                        <span className="inline-flex items-center gap-2 text-xs text-stone-500 dark:text-slate-400">
                            {showOlder ? "Gizle" : "Göster"}
                            <ChevronDown className={`w-4 h-4 transition-transform ${showOlder ? "rotate-180" : ""}`} />
                        </span>
                    </button>

                    {showOlder && (
                        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                            <AnimatePresence>
                                {olderTopics.map((topic, index) => {
                                    const topicDate = getTopicDate(topic);
                                    const storeBadge = getStoreBadge(topic);
                                    return (
                                    <motion.a
                                        key={topic.id}
                                        href={topic.clean_deal_url || topic.deal_url || topic.url}
                                        target="_blank"
                                        rel="noreferrer"
                                        initial={{ opacity: 0, y: 10 }}
                                        animate={{ opacity: 1, y: 0 }}
                                        transition={{ delay: index * 0.02, duration: 0.2, ease: "easeOut" }}
                                        className="group relative deal-card-pro rounded-2xl p-4 transition-all duration-300 cursor-pointer"
                                    >
                                        <div className="flex items-center justify-between mb-2.5">
                                            <div className="flex items-center gap-2">
                                                <span className="inline-flex items-center gap-1.5 rounded-lg border border-amber-300 bg-amber-50 px-2.5 py-1 text-[0.7rem] font-semibold uppercase tracking-wider text-amber-700 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-300">
                                                    <Flame className="w-3 h-3" />
                                                    {topic.site_name}
                                                </span>
                                                {storeBadge && (
                                                    <span className={`inline-flex items-center gap-1 text-[0.65rem] font-medium px-2 py-1 rounded-md border ${storeBadge.color}`}>
                                                        <ShoppingBag className="w-3 h-3" />
                                                        {storeBadge.label}
                                                    </span>
                                                )}
                                                {(!topic.notification_sent || topic.domain_skipped) && (
                                                    <span className="inline-flex items-center gap-1 rounded-md border border-rose-300 bg-rose-50 px-2 py-1 text-[0.65rem] font-medium text-rose-700 dark:border-rose-400/30 dark:bg-rose-500/10 dark:text-rose-300">
                                                        Gönderilmedi
                                                    </span>
                                                )}
                                            </div>
                                            <span className="flex items-center gap-1 text-[0.7rem] text-stone-500 dark:text-slate-400">
                                                <Clock className="w-3 h-3" />
                                                {formatDistanceToNow(topicDate, { addSuffix: true, locale: tr })}
                                            </span>
                                        </div>
                                        <h3 className="line-clamp-2 text-[0.9rem] font-medium leading-snug text-stone-900 transition-colors group-hover:text-black dark:text-slate-100 dark:group-hover:text-white">
                                            {topic.deal_title || topic.title}
                                        </h3>
                                        {topic.deal_title && topic.deal_title !== topic.title && (
                                            <p className="mt-0.5 line-clamp-1 text-[0.7rem] text-stone-500 dark:text-slate-400">{topic.title}</p>
                                        )}

                                        <div className="mt-2 flex items-center justify-between gap-2">
                                            {topic.deal_price ? (
                                                <span className="inline-flex items-center rounded-md border border-emerald-300 bg-emerald-50 px-2 py-1 text-[0.7rem] font-semibold text-emerald-700 dark:border-emerald-400/30 dark:bg-emerald-500/10 dark:text-emerald-300">
                                                    {topic.deal_price}
                                                </span>
                                            ) : (
                                                <span />
                                            )}
                                                <div className="flex justify-end gap-2">
                                                    <button
                                                        type="button"
                                                        onClick={(e) => handleOpenAkakce(e, topic.akakce_url)}
                                                        className="inline-flex items-center gap-1 rounded-md border border-amber-300 bg-amber-50 px-2 py-1 text-[0.65rem] font-medium text-amber-700 transition-all hover:bg-amber-100 dark:border-amber-400/30 dark:bg-amber-500/10 dark:text-amber-300 dark:hover:bg-amber-500/20"
                                                        title="Akakçe'de ara"
                                                    >
                                                        <Search className="w-3 h-3" />
                                                        Akakçe
                                                    </button>
                                                    {(!topic.notification_sent || topic.domain_skipped) && (
                                                        <button
                                                            type="button"
                                                            onClick={(e) => openSendDialog(e, topic)}
                                                            disabled={sendingId === topic.id}
                                                            className="inline-flex items-center gap-1 rounded-md border border-cyan-300 bg-cyan-50 px-2 py-1 text-[0.65rem] font-medium text-cyan-700 transition-all hover:bg-cyan-100 dark:border-cyan-400/30 dark:bg-cyan-500/10 dark:text-cyan-300 dark:hover:bg-cyan-500/20"
                                                            title="Telegram'a gönder"
                                                        >
                                                            <Send className="w-3 h-3" />
                                                            {sendingId === topic.id ? "..." : "Gönder"}
                                                        </button>
                                                    )}
                                                    <button
                                                        type="button"
                                                        onClick={(e) => handleDeleteTopic(e, topic.id)}
                                                        disabled={deletingId === topic.id}
                                                        className="inline-flex items-center gap-1 rounded-md border border-rose-300 bg-rose-50 px-2 py-1 text-[0.65rem] font-medium text-rose-700 transition-all hover:bg-rose-100 dark:border-rose-400/30 dark:bg-rose-500/10 dark:text-rose-300 dark:hover:bg-rose-500/20"
                                                        title="Kaydı sil"
                                                    >
                                                        <Trash2 className="w-3 h-3" />
                                                        {deletingId === topic.id ? "..." : "Sil"}
                                                    </button>
                                                </div>
                                        </div>
                                    </motion.a>
                                    );
                                })}
                            </AnimatePresence>
                        </div>
                    )}
                </div>
            )}

            {visibleTopics.length === 0 && (
                <div className="surface-panel col-span-full flex flex-col items-center justify-center rounded-2xl py-24">
                    <Flame className="mb-4 h-10 w-10 text-stone-400 dark:text-slate-500" />
                    <p className="text-sm text-stone-500 dark:text-slate-400">Bu filtre için kayıt bulunamadı.</p>
                </div>
            )}

            {visibleTopics.length > 0 && recentTopics.length === 0 && (
                <div className="surface-panel col-span-full flex flex-col items-center justify-center rounded-2xl py-20">
                        <Flame className="mb-4 h-10 w-10 text-stone-400 dark:text-slate-500" />
                        <p className="text-sm text-stone-500 dark:text-slate-400">Son 1 saatte yeni kayıt yok. Eski kayıtları aşağıdan açabilirsin.</p>
                </div>
            )}

            <Dialog open={sendDialogOpen} onOpenChange={setSendDialogOpen}>
                <DialogContent className="surface-panel border-stone-300 bg-white/95 text-stone-900 dark:border-slate-700 dark:bg-slate-900 sm:max-w-md">
                    <DialogHeader>
                        <DialogTitle>Telegram'a Gönder</DialogTitle>
                        <DialogDescription className="text-stone-500 dark:text-slate-400">
                            Başlık ve link otomatik geldi. Göndermeden önce düzenleyebilirsin.
                        </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-3">
                        <div className="space-y-1.5">
                            <Label htmlFor="send-title">Başlık</Label>
                            <Input
                                id="send-title"
                                value={sendTitle}
                                onChange={(e) => setSendTitle(e.target.value)}
                                placeholder="Başlık"
                                className="border-stone-300 bg-stone-50 dark:border-slate-700 dark:bg-slate-950"
                            />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="send-link">Link</Label>
                            <Input
                                id="send-link"
                                value={sendLink}
                                onChange={(e) => setSendLink(e.target.value)}
                                placeholder="https://..."
                                className="border-stone-300 bg-stone-50 dark:border-slate-700 dark:bg-slate-950"
                            />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setSendDialogOpen(false)}>
                            Vazgeç
                        </Button>
                        <Button onClick={handleForceSend} disabled={!sendTopic || sendingId === sendTopic.id}>
                            {sendTopic && sendingId === sendTopic.id ? "Gönderiliyor..." : "Gönder"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
