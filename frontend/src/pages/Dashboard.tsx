import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
    Bell,
    ChevronDown,
    Clock3,
    Filter,
    LoaderCircle,
    Search,
    Send,
    ShoppingBag,
    Trash2,
} from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { tr } from "date-fns/locale";
import { toast } from "sonner";

import { Button } from "../components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "../components/ui/dialog";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { api } from "../lib/api";

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

const SYNC_POLL_MS = 5000;

const STORE_LABELS: Record<string, { label: string; className: string }> = {
    hepsiburada: { label: "Hepsiburada", className: "border-orange-200 bg-orange-50 text-orange-700" },
    trendyol: { label: "Trendyol", className: "border-orange-200 bg-orange-50 text-orange-700" },
    amazon: { label: "Amazon", className: "border-amber-200 bg-amber-50 text-amber-800" },
    n11: { label: "N11", className: "border-rose-200 bg-rose-50 text-rose-700" },
    teknosa: { label: "Teknosa", className: "border-red-200 bg-red-50 text-red-700" },
    mediamarkt: { label: "MediaMarkt", className: "border-red-200 bg-red-50 text-red-700" },
    vatan: { label: "Vatan", className: "border-emerald-200 bg-emerald-50 text-emerald-700" },
    idefix: { label: "İdefix", className: "border-sky-200 bg-sky-50 text-sky-700" },
};

const GENERIC_STORE_BADGE = {
    className: "border-stone-200 bg-stone-100 text-stone-700",
};

const parseApiDate = (value: string) => {
    const normalized = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`;
    return new Date(normalized);
};

const getTopicDate = (topic: Topic) => parseApiDate(topic.source_date || topic.scraped_at);

const formatDealPrice = (price: string) =>
    /(?:TL|₺)/i.test(price) ? price : `${price} TL`;

const errorMessage = (error: unknown, fallback: string) =>
    error instanceof Error && error.message ? error.message : fallback;

const getStoreBadge = (topic: Topic) => {
    const url = topic.clean_deal_url || topic.deal_url || topic.url;
    try {
        const hostname = new URL(url).hostname.toLowerCase();
        const normalizedHostname = hostname.replace(/^www\./, "");
        for (const [key, value] of Object.entries(STORE_LABELS)) {
            if (normalizedHostname.includes(key)) {
                return {
                    label: value.label,
                    className: value.className,
                    faviconUrl: `https://www.google.com/s2/favicons?domain=${normalizedHostname}&sz=32`,
                };
            }
        }
        const label = normalizedHostname.split(".")[0] || normalizedHostname;
        return {
            label: label.charAt(0).toUpperCase() + label.slice(1),
            className: GENERIC_STORE_BADGE.className,
            faviconUrl: `https://www.google.com/s2/favicons?domain=${normalizedHostname}&sz=32`,
        };
    } catch {
        return null;
    }
};

const playNotificationSound = () => {
    try {
        const context = new AudioContext();
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.frequency.setValueAtTime(880, context.currentTime);
        oscillator.frequency.setValueAtTime(1174, context.currentTime + 0.12);
        gain.gain.setValueAtTime(0.18, context.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, context.currentTime + 0.35);
        oscillator.start(context.currentTime);
        oscillator.stop(context.currentTime + 0.35);
    } catch {
        return;
    }
};

interface DealCardProps {
    topic: Topic;
    sending: boolean;
    deleting: boolean;
    onSend: (topic: Topic) => void;
    onDelete: (topicId: number) => void;
}

function DealCard({ topic, sending, deleting, onSend, onDelete }: DealCardProps) {
    const storeBadge = getStoreBadge(topic);
    const productUrl = topic.clean_deal_url || topic.deal_url || topic.url;
    const needsAttention = !topic.notification_sent || topic.domain_skipped;
    const [badgeIconFailed, setBadgeIconFailed] = useState(false);

    useEffect(() => {
        setBadgeIconFailed(false);
    }, [storeBadge?.faviconUrl]);

    return (
        <article
            className="deal-card-pro flex min-h-[190px] flex-col rounded-lg p-4"
        >
            <div className="mb-3 flex min-h-6 items-start justify-between gap-3">
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="max-w-[150px] truncate rounded-md bg-[#102a43] px-2 py-1 text-[11px] font-semibold text-white shadow-[0_4px_12px_rgba(16,42,67,0.25)]">
                        {topic.site_name}
                    </span>
                    {storeBadge && (
                        <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[10px] font-semibold ${storeBadge.className}`}>
                            {!badgeIconFailed ? (
                                <img
                                    src={storeBadge.faviconUrl}
                                    alt={`${storeBadge.label} logo`}
                                    className="h-3 w-3 rounded-sm"
                                    loading="lazy"
                                    onError={() => setBadgeIconFailed(true)}
                                />
                            ) : (
                                <ShoppingBag className="h-3 w-3" />
                            )}
                            {storeBadge.label}
                        </span>
                    )}
                </div>
                <span className="inline-flex shrink-0 items-center gap-1 text-[11px] text-stone-500">
                    <Clock3 className="h-3 w-3" />
                    {formatDistanceToNow(getTopicDate(topic), { addSuffix: true, locale: tr })}
                </span>
            </div>

            <a
                href={productUrl}
                target="_blank"
                rel="noreferrer"
                className="line-clamp-2 text-sm font-semibold leading-5 text-stone-900 transition hover:text-emerald-800"
            >
                {topic.deal_title || topic.title}
            </a>
            {topic.deal_title && topic.deal_title !== topic.title && (
                <p className="mt-1 line-clamp-1 text-[11px] text-stone-500">{topic.title}</p>
            )}

            <div className="mt-auto flex items-end justify-between gap-3 pt-4">
                <div>
                    <p className="text-[10px] font-semibold uppercase text-stone-400">Fiyat</p>
                    <p className="mt-0.5 text-base font-bold text-stone-900">
                        {topic.deal_price ? formatDealPrice(topic.deal_price) : "Bulunamadı"}
                    </p>
                </div>
                <div className="flex h-9 shrink-0 items-center gap-1">
                    <a
                        href={topic.akakce_url}
                        target="_blank"
                        rel="noreferrer"
                        title="Akakçe'de karşılaştır"
                        className="inline-flex h-9 items-center gap-1.5 rounded-md border border-cyan-200 bg-cyan-50 px-2.5 text-xs font-bold text-cyan-900 transition hover:bg-cyan-100 dark:border-cyan-400/55 dark:bg-cyan-500/18 dark:text-cyan-100 dark:hover:bg-cyan-500/30"
                    >
                        <Search className="h-3.5 w-3.5" />
                        Akakçe
                    </a>
                    {needsAttention && (
                        <button
                            type="button"
                            onClick={() => onSend(topic)}
                            disabled={sending}
                            title="Telegram'a gönder"
                            aria-label="Telegram'a gönder"
                            className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-stone-200 text-stone-600 transition hover:border-emerald-300 hover:text-emerald-700 disabled:opacity-50"
                        >
                            {sending ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                        </button>
                    )}
                    <button
                        type="button"
                        onClick={() => onDelete(topic.id)}
                        disabled={deleting}
                        title="Fırsatı sil"
                        aria-label="Fırsatı sil"
                        className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-stone-200 text-stone-500 transition hover:border-rose-300 hover:text-rose-600 disabled:opacity-50"
                    >
                        {deleting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                    </button>
                </div>
            </div>
        </article>
    );
}

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
    const [notificationPermission, setNotificationPermission] = useState<NotificationPermission>(
        typeof Notification !== "undefined" ? Notification.permission : "denied",
    );
    const lastScrapeCompletedRef = useRef<string | null>(null);
    const knownTopicIdsRef = useRef<Set<number> | null>(null);

    const requestNotificationPermission = useCallback(async () => {
        if (typeof Notification === "undefined" || Notification.permission !== "default") return;
        setNotificationPermission(await Notification.requestPermission());
    }, []);

    const notifyNewTopics = useCallback((newTopics: Topic[]) => {
        if (newTopics.length === 0) return;
        playNotificationSound();
        if (typeof Notification === "undefined" || Notification.permission !== "granted") return;
        for (const topic of newTopics) {
            const price = topic.deal_price ? ` - ${formatDealPrice(topic.deal_price)}` : "";
            new Notification(topic.site_name, {
                body: `${topic.deal_title || topic.title}${price}`,
                icon: "/favicon.ico",
                tag: `topic-${topic.id}`,
            });
        }
    }, []);

    const fetchTopics = useCallback(async () => {
        try {
            const data = await api.get<Topic[]>("/dashboard/topics");
            if (knownTopicIdsRef.current !== null) {
                notifyNewTopics(data.filter((topic) => !knownTopicIdsRef.current?.has(topic.id)));
            }
            knownTopicIdsRef.current = new Set(data.map((topic) => topic.id));
            setTopics(data);
        } catch (error) {
            console.error(error);
        } finally {
            setLoading(false);
        }
    }, [notifyNewTopics]);

    const pollSyncStatus = useCallback(async () => {
        try {
            const status = await api.get<SyncStatus>("/dashboard/sync-status");
            if (
                status.last_scrape_completed_at &&
                lastScrapeCompletedRef.current !== status.last_scrape_completed_at
            ) {
                lastScrapeCompletedRef.current = status.last_scrape_completed_at;
                await fetchTopics();
            }
        } catch (error) {
            console.error(error);
        }
    }, [fetchTopics]);

    useEffect(() => {
        let cancelled = false;
        const bootstrap = async () => {
            try {
                const status = await api.get<SyncStatus>("/dashboard/sync-status");
                if (cancelled) return;
                lastScrapeCompletedRef.current = status.last_scrape_completed_at;
                await fetchTopics();
            } catch (error) {
                console.error(error);
                if (!cancelled) setLoading(false);
            }
        };
        void requestNotificationPermission();
        void bootstrap();
        const interval = window.setInterval(() => void pollSyncStatus(), SYNC_POLL_MS);
        return () => {
            cancelled = true;
            window.clearInterval(interval);
        };
    }, [fetchTopics, pollSyncStatus, requestNotificationPermission]);

    const siteOptions = useMemo(
        () => ["TUMU", ...Array.from(new Set(topics.map((topic) => topic.site_name)))],
        [topics],
    );

    const visibleTopics = useMemo(
        () => selectedSite === "TUMU" ? topics : topics.filter((topic) => topic.site_name === selectedSite),
        [selectedSite, topics],
    );

    const [recentTopics, olderTopics] = useMemo(() => {
        const recent: Topic[] = [];
        const older: Topic[] = [];
        const oneHourAgo = Date.now() - 60 * 60 * 1000;
        for (const topic of visibleTopics) {
            (getTopicDate(topic).getTime() >= oneHourAgo ? recent : older).push(topic);
        }
        return [recent, older];
    }, [visibleTopics]);

    const openSendDialog = (topic: Topic) => {
        setSendTopic(topic);
        setSendTitle(topic.deal_title || topic.title);
        setSendLink(topic.clean_deal_url || topic.deal_url || topic.url);
        setSendDialogOpen(true);
    };

    const handleForceSend = async () => {
        if (!sendTopic) return;
        setSendingId(sendTopic.id);
        try {
            await api.post(`/dashboard/topics/${sendTopic.id}/send`, { title: sendTitle, link: sendLink });
            setTopics((current) => current.map((topic) => topic.id === sendTopic.id
                ? { ...topic, notification_sent: true, domain_skipped: false }
                : topic));
            setSendDialogOpen(false);
            toast.success("Bildirim gönderildi.");
        } catch (error) {
            toast.error(errorMessage(error, "Bildirim gönderilemedi."));
        } finally {
            setSendingId(null);
        }
    };

    const handleDeleteTopic = async (topicId: number) => {
        const runDelete = async () => {
            setDeletingId(topicId);
            try {
                await api.delete(`/dashboard/topics/${topicId}`);
                setTopics((current) => current.filter((topic) => topic.id !== topicId));
                toast.success("Fırsat silindi.");
            } catch (error) {
                toast.error(errorMessage(error, "Fırsat silinemedi."));
            } finally {
                setDeletingId(null);
            }
        };

        toast.warning("Fırsat silinsin mi?", {
            description: "Bu işlem geri alınamaz.",
            action: {
                label: "Sil",
                onClick: () => {
                    void runDelete();
                },
            },
            cancel: {
                label: "Vazgeç",
                onClick: () => undefined,
            },
            duration: 10000,
        });
    };

    return (
        <section aria-labelledby="deals-title" className="dashboard-theme space-y-4 pb-10">
            <div className="surface-panel flex flex-col justify-between gap-3 rounded-xl p-5 sm:flex-row sm:items-end">
                <div>
                    <p className="mb-2 text-xs font-bold uppercase tracking-[0.16em] text-cyan-700">Canlı akış</p>
                    <h1 id="deals-title" className="hero-title section-hero-title text-[#102a43]">Güncel fırsatlar</h1>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    {notificationPermission !== "granted" && typeof Notification !== "undefined" && (
                        <button type="button" onClick={requestNotificationPermission} className="inline-flex h-9 items-center gap-2 rounded-md border border-cyan-200 bg-white/80 px-3 text-xs font-semibold text-slate-700 transition hover:border-cyan-400 hover:text-[#102a43]">
                            <Bell className="h-4 w-4 text-cyan-600" /> Bildirimleri aç
                        </button>
                    )}
                    <label className="relative flex h-9 items-center rounded-md border border-cyan-200 bg-white/80 pl-9 pr-2">
                        <Filter className="pointer-events-none absolute left-3 h-4 w-4 text-cyan-700" />
                        <span className="sr-only">Kaynak filtresi</span>
                        <select value={selectedSite} onChange={(event) => setSelectedSite(event.target.value)} className="h-full min-w-32 appearance-none bg-transparent pr-7 text-xs font-semibold text-slate-700 outline-none">
                            {siteOptions.map((site) => (
                                <option key={site} value={site}>{site === "TUMU" ? "Tüm kaynaklar" : site}</option>
                            ))}
                        </select>
                        <ChevronDown className="pointer-events-none absolute right-2 h-3.5 w-3.5 text-cyan-700" />
                    </label>
                </div>
            </div>

            {loading ? (
                <div className="surface-panel flex h-48 items-center justify-center rounded-xl">
                    <LoaderCircle className="h-6 w-6 animate-spin text-emerald-700" />
                </div>
            ) : visibleTopics.length === 0 ? (
                <div className="surface-panel flex h-40 flex-col items-center justify-center rounded-lg text-center">
                    <ShoppingBag className="mb-2 h-5 w-5 text-stone-400" />
                    <p className="text-sm font-semibold text-stone-700">Bu kaynakta fırsat bulunamadı</p>
                </div>
            ) : (
                <>
                    {recentTopics.length > 0 && (
                        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                            {recentTopics.map((topic) => (
                                <DealCard key={topic.id} topic={topic} sending={sendingId === topic.id} deleting={deletingId === topic.id} onSend={openSendDialog} onDelete={handleDeleteTopic} />
                            ))}
                        </div>
                    )}

                    {olderTopics.length > 0 && (
                        <div className="surface-panel rounded-xl p-3">
                            <button type="button" onClick={() => setShowOlder((current) => !current)} className="flex h-10 w-full items-center justify-between rounded-md px-2 text-sm font-semibold text-slate-700 transition hover:bg-slate-50 dark:text-slate-200 dark:hover:bg-slate-800/70">
                                <span>Eski fırsatlar ({olderTopics.length})</span>
                                <ChevronDown className={`h-4 w-4 transition-transform ${showOlder ? "rotate-180" : ""}`} />
                            </button>
                            {showOlder && (
                                <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                                    {olderTopics.map((topic) => (
                                        <DealCard key={topic.id} topic={topic} sending={sendingId === topic.id} deleting={deletingId === topic.id} onSend={openSendDialog} onDelete={handleDeleteTopic} />
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </>
            )}

            <Dialog open={sendDialogOpen} onOpenChange={setSendDialogOpen}>
                <DialogContent className="surface-panel border-slate-200 bg-white/90 text-stone-900 sm:max-w-md">
                    <DialogHeader>
                        <DialogTitle>Telegram'a gönder</DialogTitle>
                        <DialogDescription className="text-stone-500">Gönderilecek başlık ve bağlantı</DialogDescription>
                    </DialogHeader>
                    <div className="space-y-3">
                        <div className="space-y-1.5">
                            <Label htmlFor="send-title">Başlık</Label>
                            <Input id="send-title" value={sendTitle} onChange={(event) => setSendTitle(event.target.value)} className="border-stone-300 bg-stone-50" />
                        </div>
                        <div className="space-y-1.5">
                            <Label htmlFor="send-link">Bağlantı</Label>
                            <Input id="send-link" value={sendLink} onChange={(event) => setSendLink(event.target.value)} className="border-stone-300 bg-stone-50" />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setSendDialogOpen(false)}>Vazgeç</Button>
                        <Button onClick={handleForceSend} disabled={!sendTopic || sendingId === sendTopic?.id} className="bg-[#19382f] text-white hover:bg-[#245144]">
                            {sendTopic && sendingId === sendTopic.id ? "Gönderiliyor" : "Gönder"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </section>
    );
}
