// Create an axios-like api wrapper but with native fetch
const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

export const api = {
    get: async <T>(endpoint: string): Promise<T> => {
        const res = await fetch(`${BASE_URL}${endpoint}`);
        if (!res.ok) throw new Error("Network response was not ok");
        return res.json();
    },
    post: async <T>(endpoint: string, data: any): Promise<T> => {
        const res = await fetch(`${BASE_URL}${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        if (!res.ok) throw new Error("Network response was not ok");
        return res.json();
    },
    put: async <T>(endpoint: string, data: any): Promise<T> => {
        const res = await fetch(`${BASE_URL}${endpoint}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data),
        });
        if (!res.ok) throw new Error("Network response was not ok");
        return res.json();
    },
    delete: async (endpoint: string): Promise<void> => {
        const res = await fetch(`${BASE_URL}${endpoint}`, {
            method: "DELETE",
        });
        if (!res.ok) throw new Error("Network response was not ok");
    },
    patch: async <T>(endpoint: string, data?: any): Promise<T> => {
        const res = await fetch(`${BASE_URL}${endpoint}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: data ? JSON.stringify(data) : undefined,
        });
        if (!res.ok) throw new Error("Network response was not ok");
        return res.json();
    },
};
