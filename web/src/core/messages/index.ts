export * from "./types";
export * from "./merge-message";


export interface Conversation {
  id: string;
  title: string;
  count: number;
  date: string;
  category: string;
  data_type: string;
}
