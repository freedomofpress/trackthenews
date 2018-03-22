create table articles (
    id          integer primary key autoincrement not null,
    title       text,
    outlet      text,
    url         text,
    tweeted     boolean,
    recorded_at datetime
);
