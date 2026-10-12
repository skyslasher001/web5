export type * from './bridge';
export type { components, paths } from './api';
export { EVENT_TYPES } from './events';
export type { EventType } from './events';

import type { components } from './api';

type Schemas = components['schemas'];
export type CoreEvent = Schemas['Event'];
export type Project = Schemas['Project'];
export type Message = Schemas['Message'];
export type Conversation = Schemas['Conversation'];
export type Vitals = Schemas['Vitals'];
export type HardwareInfo = Schemas['HardwareInfo'];
export type Recommendation = Schemas['Recommendation'];
export type ModelsInfo = Schemas['ModelsInfo'];
export type AgentInfo = Schemas['AgentInfo'];
export type ChatSendResponse = Schemas['ChatSendResponse'];
export type WsTicket = Schemas['WsTicket'];
export type EventPage = Schemas['EventPage'];
