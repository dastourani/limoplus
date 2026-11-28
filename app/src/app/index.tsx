import { Redirect } from 'expo-router';

/** First screen: always the home page; a newcomer picks a major in the row at its top. */
export default function Start() {
  return <Redirect href="/home" />;
}
